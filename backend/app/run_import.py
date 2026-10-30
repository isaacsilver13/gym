"""Explicit, resumable Endurain file import using an upload-only API key.

Default is a local dry run. --apply uploads original files using stable content
keys and polls the ingestion job. No automatic job or cloud account is created.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import httpx

from app.training import safe_url


def bind_manifest(manifest: dict, base: str, key: str):
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    if manifest["url"] != base:
        raise ValueError("Manifest belongs to another Endurain server")
    previous = manifest.get("credential_sha256")
    if previous != fingerprint and (previous is not None or manifest["files"]):
        raise ValueError("Manifest belongs to another upload credential; use a new manifest")
    manifest["credential_sha256"] = fingerprint


def import_file(client, base: str, key: str, path: Path, prior: dict | None = None):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    headers = {"X-API-Key": key, "Idempotency-Key": "training-hub:" + digest}
    if prior and prior.get("status") == "completed":
        return prior
    job = prior
    if not job or not job.get("id"):
        with path.open("rb") as stream:
            response = client.post(base + "/api/v1/activities/upload", headers=headers,
                                   files={"file": (path.name, stream, "application/octet-stream")})
        response.raise_for_status()
        job = response.json()
    return {"sha256": digest, "id": job["id"], "status": job["status"],
            "activity_ids": job.get("activity_ids", [])}


def poll_job(client, base, key, record):
    response = client.get(base + "/api/v1/activities/ingestion-jobs/" + record["id"],
                          headers={"X-API-Key": key})
    response.raise_for_status()
    job = response.json()
    return {**record, "status": job["status"], "activity_ids": job.get("activity_ids", []),
            "error_code": job.get("error_code")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    base = safe_url(args.url)
    manifest = json.loads(args.manifest.read_text()) if args.manifest.exists() else {
        "format": 1, "url": base, "files": {},
    }
    if manifest["url"] != base:
        parser.error("Manifest belongs to another Endurain server")
    for path in args.files:
        if not path.is_file() or path.suffix.lower() not in {".fit", ".gpx", ".tcx"}:
            parser.error("Each input must be an existing FIT, GPX or TCX file")
    if not args.apply:
        print(json.dumps({"mode": "dry_run", "files": len(args.files), "url": base}))
        return
    key = os.environ.get("ENDURAIN_UPLOAD_KEY", "")
    if not key:
        parser.error("Set ENDURAIN_UPLOAD_KEY securely in the process environment")
    try:
        bind_manifest(manifest, base, key)
    except ValueError as error:
        parser.error(str(error))
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temp = args.manifest.with_suffix(".tmp")
        fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
        os.replace(temp, args.manifest)

    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            for path in args.files:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                record = import_file(client, base, key, path, manifest["files"].get(digest))
                manifest["files"][digest] = record
                save()  # Save the accepted job before polling or moving to the next file.
                for _ in range(30):
                    if record["status"] in {"completed", "failed"}:
                        break
                    time.sleep(1)
                    record = poll_job(client, base, key, record)
                    manifest["files"][digest] = record
                    save()
    except (httpx.HTTPError, ValueError, KeyError):
        parser.exit(1, "Import interrupted. Re-run using the same manifest to resume.\n")
    counts = {}
    for item in manifest["files"].values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(json.dumps({"jobs": counts}))
    if any(status != "completed" for status in counts):
        parser.exit(1, "Some jobs are pending or failed; inspect the manifest and Endurain.\n")


if __name__ == "__main__":
    main()
