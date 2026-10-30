"""Create a private Apple Health connection from an existing Endurain session."""

import argparse
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path

import httpx

from app.training import safe_url
from app.training_tokens import EndurainSession

ENDPOINT = "/api/v1/integrations/apple-health/workouts"


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def save_connection(config, phone, *, owner, base, user_id, upload_key, receiver):
    if config.exists() or phone.exists():
        raise ValueError("Use new private paths; existing credentials will not be overwritten")
    base = safe_url(base)
    receiver = safe_url(receiver, public=True)
    if not base or not receiver or not receiver.startswith("https://"):
        raise ValueError("Phone receiver requires HTTPS")
    if not receiver.endswith(ENDPOINT) or not owner or not str(user_id).isdigit() or not upload_key:
        raise ValueError("Invalid connection parameters")
    token = secrets.token_urlsafe(48)
    write_private(config, {"format": 1, "owner": owner, "endurain_url": base,
                           "endurain_user_id": str(user_id), "upload_key": upload_key,
                           "token_sha256": hashlib.sha256(token.encode()).hexdigest()})
    write_private(phone, {"url": receiver, "headers": {"Authorization": "Bearer " + token},
                          "format": "JSON", "export_version": 2, "data_type": "Workouts"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--endurain-url", required=True)
    parser.add_argument("--endurain-user-id", required=True)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--receiver", required=True)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--phone", required=True, type=Path)
    args = parser.parse_args()
    if args.config.exists() or args.phone.exists():
        parser.error("Use new private paths; existing credentials will not be overwritten")
    try:
        base = safe_url(args.endurain_url)
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            profile = EndurainSession(str(args.session), base, client).get("/api/v1/profile")
            if str(profile["id"]) != args.endurain_user_id:
                raise ValueError("Session belongs to another Endurain profile")
            if profile.get("default_activity_visibility") != "private":
                raise ValueError("Set Endurain default activity visibility to private first")
            password = getpass.getpass("Endurain password (for upload-key creation): ")
            payload = {"name": "Apple Health private receiver", "scopes": ["activities:upload"],
                       "current_password": password}
            if profile.get("mfa_enabled"):
                payload["mfa_code"] = getpass.getpass("MFA code: ")
            tokens = json.loads(args.session.read_text(encoding="utf-8"))
            response = client.post(base + "/api/v1/profile/api_keys", json=payload, headers={
                "X-Client-Type": "mobile", "Authorization": "Bearer " + tokens["access_token"]})
            response.raise_for_status()
            created = response.json()
            save_connection(args.config, args.phone, owner=args.owner, base=base,
                            user_id=args.endurain_user_id, upload_key=created["key"],
                            receiver=args.receiver)
    except (OSError, httpx.HTTPError, ValueError, TypeError, KeyError):
        parser.exit(1, "Setup failed. Check private paths, profile/privacy and credentials.\n"
                    "If a key was created before a local write failed, revoke that unused key.\n")
    print("Connection and phone settings saved privately. No credentials printed.")


if __name__ == "__main__":
    main()
