"""Endurain mobile-session authentication with atomic rotating-token storage.

Run one hub process when using this local credential file. The token is a full
user session: the adapter exposes only reads, but the secret itself is not scoped.
"""

import argparse
import getpass
import json
import os
import threading
from pathlib import Path

import httpx

_lock = threading.Lock()


def save_tokens(path: Path, base: str, payload: dict):
    if not payload.get("access_token") or not payload.get("refresh_token"):
        raise ValueError("The server did not return a mobile token pair")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    data = {"url": base, "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"]}
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class EndurainSession:
    def __init__(self, token_file: str, base: str, client):
        self.path, self.base, self.client = Path(token_file), base, client

    def get(self, path: str, params=None):
        # Serialize refresh and read so simultaneous requests do not race rotation.
        with _lock:
            tokens = json.loads(self.path.read_text(encoding="utf-8"))
            if tokens["url"] != self.base:
                raise ValueError("Credential file belongs to a different server")
            headers = {"Authorization": "Bearer " + tokens["access_token"],
                       "X-Client-Type": "mobile"}
            response = self.client.get(self.base + path, headers=headers, params=params)
            if response.status_code == 401:
                refresh = self.client.post(self.base + "/api/v1/auth/refresh", headers={
                    "Authorization": "Bearer " + tokens["refresh_token"],
                    "X-Client-Type": "mobile",
                })
                refresh.raise_for_status()
                rotated = refresh.json()
                save_tokens(self.path, self.base, rotated)
                headers["Authorization"] = "Bearer " + rotated["access_token"]
                response = self.client.get(self.base + path, headers=headers, params=params)
            response.raise_for_status()
            return response.json()


def main():
    parser = argparse.ArgumentParser(description="Connect a local-password Endurain account")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    # Import here to avoid a circular import in the HTTP adapter.
    from app.training import safe_url

    base = safe_url(args.url)
    if args.out.exists():
        parser.error("Credential file already exists; use a new path to reconnect")
    username = input("Endurain username: ")
    password = getpass.getpass("Endurain password: ")
    headers = {"X-Client-Type": "mobile"}
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.post(base + "/api/v1/auth/login", headers=headers,
                                   data={"username": username, "password": password})
            response.raise_for_status()
            tokens = response.json()
            if tokens.get("mfa_required"):
                response = client.post(base + "/api/v1/auth/mfa/verify", headers=headers,
                                       json={"username": username,
                                             "mfa_code": getpass.getpass("MFA code: ")})
                response.raise_for_status()
                tokens = response.json()
            save_tokens(args.out, base, tokens)
    except (httpx.HTTPError, ValueError, KeyError):
        parser.exit(1, "Connection failed. Check your server/account; no credentials printed.\n")
    print("Endurain session saved. Protect this file as a full sign-in credential.")


if __name__ == "__main__":
    main()
