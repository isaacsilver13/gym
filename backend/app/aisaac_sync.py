"""Outbound-only bridge: AIsaac staging -> one canonical destination -> weekly snapshots."""

import asyncio
import copy
import hashlib
import json
import logging
from contextlib import closing
from datetime import date, datetime
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import httpx

from app.apple_health import AppleHealthSettings, connect, enqueue
from app.apple_health_fit import normalize, to_fit
from app.config import _setting
from app.training import TrainingSettings, build_summary, safe_url

logger = logging.getLogger(__name__)


class DestinationDeleted(ValueError):
    pass


def apple_uuid(source_id):
    try:
        return str(UUID(source_id))  # same identity as direct Health Auto Export uploads
    except ValueError:
        return str(uuid5(NAMESPACE_URL, "aisaac-shortcut:" + source_id))


def strength_workout(state, payload, source, digest):
    """No catalogue guesses, PRs, inferred sets, or inferred duration."""
    wid = "aisaac-" + str(uuid5(NAMESPACE_URL, source))
    for workout in state.get("workouts", []):
        if workout.get("id") == wid:
            return None  # Includes records explicitly restored after a delete/reset.
    if state.get("deleted", {}).get("workouts", {}).get(wid, 0) > 0 or wid in state.get(
        "resetIds", {}
    ).get("workouts", []):
        raise DestinationDeleted("Workout was deleted at destination")
    moment = datetime.fromisoformat(payload["start"])
    if moment.tzinfo is None:
        raise ValueError("Missing workout timezone")
    if (
        state.get("resetAt")
        and not state.get("resetIds")
        and moment.timestamp() * 1000 <= state["resetAt"]
    ):
        raise DestinationDeleted("Workout predates destination reset")
    unit = state.get("unit", "kg")
    if unit not in {"kg", "lb"}:
        raise ValueError("Unknown destination weight unit")
    factor = 0.45359237 if unit == "kg" else 1
    entries, summaries = [], []
    custom = state.setdefault("customEx", [])
    for exercise in payload.get("exercises", []):
        eid = "aisaac-ex-" + str(
            uuid5(NAMESPACE_URL, source.split(":session:")[0] + ":exercise:" + exercise["id"])
        )
        if not any(e.get("id") == eid for e in custom):
            custom.append(
                {
                    "id": eid,
                    "n": exercise["name"],
                    "bp": "",
                    "desc": "AIsaac exercise. Load is as entered; "
                    "equipment and per-hand meaning are not inferred.",
                }
            )
        sets = exercise.get("sets")
        if sets is None:
            summaries.append({"name": exercise["name"], **exercise["summary"]})
        else:
            entries.append(
                {
                    "id": eid,
                    "sets": [
                        {"w": s["weight_lb"] * factor, "r": s["reps_done"], "done": True}
                        for s in sets
                    ],
                    "target": {"id": eid},
                    "topW": max(s["weight_lb"] * factor for s in sets),
                }
            )
    result = {
        "id": wid,
        "name": payload["name"],
        "d": moment.astimezone(ZoneInfo("America/Chicago")).date().isoformat(),
        "start": int(moment.timestamp() * 1000),
        "entries": entries,
        "prs": [],
        "source": "aisaac",
        "source_digest": digest,
        "summary_only": not entries,
        "note": "Imported from AIsaac / Apple Health. Only explicitly logged sets count.",
    }
    if payload.get("end"):
        result["end"] = int(datetime.fromisoformat(payload["end"]).timestamp() * 1000)
    else:
        result["note"] += " Start marks log time; workout duration was not recorded."
    if summaries:
        result["note"] += " Earlier exercise summaries (not sets): " + json.dumps(summaries)
    return result


def send_strength(client, cfg, payload, source, digest):
    base = safe_url(cfg.opengym_url)
    if not base or not cfg.opengym_token or not cfg.opengym_uid:
        raise ValueError("OpenGym is not configured")
    headers = {"Authorization": "Bearer " + cfg.opengym_token}
    me = client.get(base + "/api/me", headers=headers)
    me.raise_for_status()
    if str(me.json().get("user", {}).get("id")) != cfg.opengym_uid:
        raise ValueError("OpenGym owner mismatch")
    for _ in range(3):
        response = client.get(base + "/api/data", headers=headers)
        response.raise_for_status()
        document = response.json()
        state = copy.deepcopy(document["state"])
        if state is None:
            state = {"unit": "lb", "workouts": [], "routines": [], "customEx": [], "week": {}}
        if not isinstance(state, dict) or not isinstance(document.get("rev"), int):
            raise ValueError("Invalid OpenGym state")
        workout = strength_workout(state, payload, source, digest)
        if workout is None:
            return
        state.setdefault("workouts", []).append(workout)
        response = client.put(
            base + "/api/data",
            headers=headers,
            json={"state": state, "baseRev": document["rev"], "baseWid": state.get("_wid", "")},
        )
        if response.status_code != 409:
            response.raise_for_status()
            return
    raise ValueError("OpenGym revision conflict")


def send_cardio(cfg, payload):
    value = {**payload, "id": apple_uuid(payload["id"])}
    canonical = normalize(value)
    if canonical is None:
        raise ValueError("Unsupported cardio type")
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    enqueue(cfg, [(canonical["id"], digest, to_fit(canonical))], preserve_existing=True)
    with closing(connect(cfg)) as db:
        row = db.execute(
            "SELECT state,changed FROM workouts WHERE source_id=?", (canonical["id"],)
        ).fetchone()
    if row["state"] == "completed":
        return "delivered", "changed_export" if row["changed"] else None
    if row["state"] == "failed":
        # Keep polling: an operator can repair credentials and retry the original job.
        return "retry", "destination_rejected"
    return "processing", "changed_export" if row["changed"] else None


def sync_once(client=None):
    base = safe_url(_setting("AISAAC_SYNC_URL", ""))
    token = _setting("AISAAC_SYNC_TOKEN", "")
    if not base or not token:
        return
    cfg = TrainingSettings.load()
    expected_owner = _setting("AISAAC_OWNER", "") or cfg.username
    owned = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
    headers = {"X-Training-Sync-Token": token}

    def call(method, path, **kwargs):
        response = client.request(
            method, base + "/api/v1/gym/sync" + path, headers=headers, **kwargs
        )
        response.raise_for_status()
        return response.json()

    try:
        batch = call("GET", "/jobs")
        if not expected_owner or batch["owner"] != expected_owner:
            raise ValueError("AIsaac owner mismatch")
        for job in batch["jobs"]:
            state, error = "retry", None
            try:
                if job["destination"] == "opengym":
                    send_strength(
                        client,
                        cfg,
                        job["payload"],
                        base + ":" + expected_owner + ":" + job["source_id"],
                        job["digest"],
                    )
                    state = "delivered"
                elif job["destination"] == "endurain":
                    apple = AppleHealthSettings.load()
                    if apple is None:
                        raise ValueError("Endurain upload is not configured")
                    state, error = send_cardio(apple, job["payload"])
                else:
                    state, error = "failed", "destination_rejected"
            except DestinationDeleted:
                state, error = "failed", "deleted_at_destination"
            except (httpx.HTTPError, OSError):
                error = "destination_unavailable"
            except (ValueError, TypeError, KeyError):
                error = "configuration_error"
            call(
                "POST",
                "/receipts",
                json={
                    "id": job["id"],
                    "digest": job["digest"],
                    "destination": job["destination"],
                    "state": state,
                    "error": error,
                },
            )
        requested = call("GET", "/weeks")
        if requested["owner"] != expected_owner:
            raise ValueError("AIsaac owner mismatch")
        for week in requested["weeks"]:
            summary = build_summary(cfg, date.fromisoformat(week), client)
            call(
                "POST",
                "/snapshots",
                json={
                    k: summary[k]
                    for k in (
                        "generated_at",
                        "week_start",
                        "week_end_exclusive",
                        "timezone",
                        "sources",
                        "totals",
                        "activities",
                    )
                },
            )
    finally:
        if owned:
            client.close()


async def worker():
    while True:
        try:
            await asyncio.to_thread(sync_once)
        except Exception as exc:
            logger.error("AIsaac training sync: %s", type(exc).__name__)
        await asyncio.sleep(60)
