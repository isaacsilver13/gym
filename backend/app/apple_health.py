"""Private, account-bound durable Apple Health outbox and Endurain worker."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import httpx

from app.config import _setting
from app.training import safe_url


@dataclass(frozen=True)
class AppleHealthSettings:
    owner: str
    endurain_url: str
    endurain_user_id: str
    token_sha256: str = field(repr=False)
    upload_key: str = field(repr=False)
    queue: Path

    @property
    def binding(self):
        identity = [self.owner, self.endurain_url, self.endurain_user_id]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def authorized(self, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            return False
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        return hmac.compare_digest(digest, self.token_sha256)

    @classmethod
    def load(cls):
        path = _setting("APPLE_HEALTH_CONFIG_FILE", "")
        if not path:
            return None
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        keys = ("owner", "endurain_url", "endurain_user_id", "token_sha256", "upload_key")
        if not isinstance(config, dict) or any(
            not isinstance(config.get(key), str) or not config[key] for key in keys
        ):
            raise ValueError("Invalid Apple Health configuration")
        url = safe_url(config["endurain_url"])
        if (config.get("format") != 1 or not config.get("owner")
                or config["owner"] != _setting("TRAINING_USERNAME", "")
                or str(config["endurain_user_id"]) != _setting("ENDURAIN_USER_ID", "")
                or url != safe_url(_setting("ENDURAIN_URL", ""))
                or len(config["token_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in config["token_sha256"])
                or not config["endurain_user_id"].isdigit()):
            raise ValueError("Apple Health account mapping is invalid")
        return cls(config["owner"], url, str(config["endurain_user_id"]),
                   config["token_sha256"], config["upload_key"],
                   Path(_setting("APPLE_HEALTH_QUEUE", "runtime/apple-health.sqlite")))


def connect(cfg):
    cfg.queue.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Explicit permissions on creation; inherited account ACLs apply on Windows.
    fd = os.open(cfg.queue, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    db = sqlite3.connect(cfg.queue, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=DELETE")  # /data backup includes the complete outbox.
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS identity (binding TEXT NOT NULL)")
        row = db.execute("SELECT binding FROM identity").fetchone()
        if row is None:
            db.execute("INSERT INTO identity VALUES (?)", (cfg.binding,))
        elif row["binding"] != cfg.binding:
            raise ValueError("Outbox belongs to another account or server")
        db.execute("""CREATE TABLE IF NOT EXISTS workouts (
            source_id TEXT PRIMARY KEY, digest TEXT NOT NULL, fit BLOB,
            state TEXT NOT NULL, job_id TEXT, activity_ids TEXT NOT NULL DEFAULT '[]',
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
            lease REAL NOT NULL DEFAULT 0, error TEXT,
            changed INTEGER NOT NULL DEFAULT 0, received REAL NOT NULL, updated REAL NOT NULL
        )""")
        db.commit()
        return db
    except Exception:
        db.close()
        raise


def enqueue(cfg, prepared):
    counts = {"queued": 0, "duplicates": 0, "changed": 0}
    with closing(connect(cfg)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for source_id, digest, fit in prepared:
            row = db.execute("SELECT digest FROM workouts WHERE source_id=?",
                             (source_id,)).fetchone()
            now = time.time()
            if row:
                counts["duplicates"] += 1
                if row["digest"] != digest:
                    counts["changed"] += 1
                    db.execute("UPDATE workouts SET changed=1, updated=? WHERE source_id=?",
                               (now, source_id))
            else:
                db.execute("""INSERT INTO workouts
                    (source_id,digest,fit,state,received,updated) VALUES (?,?,?,'queued',?,?)""",
                           (source_id, digest, fit, now, now))
                counts["queued"] += 1
    return counts


def queue_status(cfg):
    with closing(connect(cfg)) as db:
        totals = {row["state"]: row["n"] for row in db.execute(
            "SELECT state,COUNT(*) AS n FROM workouts GROUP BY state")}
        changed = db.execute("SELECT COUNT(*) FROM workouts WHERE changed=1").fetchone()[0]
        recent = [dict(row) for row in db.execute("""SELECT source_id,state,error,changed,
            received,updated,activity_ids FROM workouts ORDER BY updated DESC LIMIT 10""")]
        for item in recent:
            item["activity_ids"] = json.loads(item["activity_ids"])
    return {"configured": True, "counts": totals, "changed": changed, "recent": recent}


def work_once(cfg, client=None, now=None):
    """Lease one item, submit OR poll once. Crashes resume the same idempotent job."""
    now = time.time() if now is None else now
    with closing(connect(cfg)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT * FROM workouts WHERE state IN ('queued','processing')
            AND next_attempt<=? AND lease<=? ORDER BY next_attempt,received LIMIT 1""",
                         (now, now)).fetchone()
        if row is None:
            return False
        db.execute("UPDATE workouts SET lease=? WHERE source_id=?", (now + 120, row["source_id"]))
    state, job_id, activity_ids = row["state"], row["job_id"], row["activity_ids"]
    error, attempts, delay = None, row["attempts"], 2
    owned_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
    try:
        headers = {"X-API-Key": cfg.upload_key}
        if job_id:
            response = client.get(cfg.endurain_url + "/api/v1/activities/ingestion-jobs/" + job_id,
                                  headers=headers)
        else:
            # The digest keeps retries stable but gives a replaced export its own key.
            key = hashlib.sha256(
                (cfg.binding + ":" + row["source_id"] + ":" + row["digest"]).encode()).hexdigest()
            headers["Idempotency-Key"] = "apple-health-v1:" + key
            response = client.post(cfg.endurain_url + "/api/v1/activities/upload", headers=headers,
                                   files={"file": ("apple-workout.fit", row["fit"],
                                                   "application/octet-stream")})
        response.raise_for_status()
        job = response.json()
        job_id = str(UUID(job["id"]))
        if job["status"] == "completed":
            ids = job.get("activity_ids", [])
            if not ids or len(ids) > 10 or any(type(i) is not int or i < 1 for i in ids):
                raise ValueError("Invalid activity IDs")
            state, activity_ids = "completed", json.dumps(ids)
        elif job["status"] == "failed":
            state, error = "failed", "endurain_ingestion_failed"
        elif job["status"] in {"queued", "processing", "pending", "running"}:
            state = "processing"
        else:
            raise ValueError("Invalid job status")
        attempts = 0
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            state, error = "failed", "upload_credential_rejected"
        elif 400 <= status < 500 and status not in {408, 409, 429}:
            state, error = "failed", "endurain_request_rejected"
        else:
            error = "endurain_unavailable"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        error = "endurain_unavailable"
    finally:
        if owned_client:
            client.close()
    if error and state != "failed":
        attempts += 1
        delay = min(3600, 30 * 2**min(attempts, 7))
    with closing(connect(cfg)) as db, db:
        db.execute("""UPDATE workouts SET state=?,job_id=?,activity_ids=?,attempts=?,
            next_attempt=?,lease=0,error=?,updated=?,
            fit=CASE WHEN ?='completed' THEN NULL ELSE fit END
            WHERE source_id=?""", (state, job_id, activity_ids, attempts, now + delay,
                                   error, now, state, row["source_id"]))
    return True


async def worker():
    while True:
        try:
            cfg = AppleHealthSettings.load()
            if cfg:
                for _ in range(10):
                    if not await asyncio.to_thread(work_once, cfg):
                        break
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            # Status endpoint reports configuration/storage failure. No private payload logs.
            pass
        await asyncio.sleep(3)


def retry_credentials(cfg, apply=False):
    with closing(connect(cfg)) as db, db:
        count = db.execute("SELECT COUNT(*) FROM workouts WHERE state='failed' "
                           "AND error='upload_credential_rejected'").fetchone()[0]
        if apply:
            db.execute("""UPDATE workouts SET state=CASE WHEN job_id IS NULL THEN 'queued'
                ELSE 'processing' END,error=NULL,next_attempt=0,lease=0,attempts=0
                WHERE state='failed' AND error='upload_credential_rejected'""")
    return count


def main():
    parser = argparse.ArgumentParser(description="Retry imports after fixing an upload credential")
    parser.add_argument("--apply", action="store_true", help="Default is a count-only dry run")
    args = parser.parse_args()
    try:
        cfg = AppleHealthSettings.load()
        if cfg is None:
            parser.error("Apple Health is not configured")
        count = retry_credentials(cfg, args.apply)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        parser.exit(1, "Check the private connection and outbox configuration.\n")
    print(json.dumps({"credential_failures": count, "applied": args.apply}))


if __name__ == "__main__":
    main()
