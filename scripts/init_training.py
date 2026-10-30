"""Create ignored local staging configuration without printing secrets."""

import base64
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "deployment" / ".env"
values = {
    "HUB_SESSION_SECRET": secrets.token_urlsafe(48),
    "ENDURAIN_DB_PASSWORD": secrets.token_urlsafe(36),
    "ENDURAIN_SECRET_KEY": secrets.token_urlsafe(48),
    "ENDURAIN_FERNET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "TRAINING_USERNAME": "", "OPENGYM_UID": "", "OPENGYM_TOKEN": "",
    "ENDURAIN_USER_ID": "", "ASSISTANT_READ_TOKEN": "",
}
path.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    for key, value in values.items():
        stream.write(f"{key}={value}\n")
(root / "runtime" / "connections").mkdir(parents=True, exist_ok=True)
print("Local staging configuration created. No existing files were replaced.")
