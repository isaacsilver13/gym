import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_DEFAULT_DATABASE_URL = "sqlite:///./gym_tracker_dev.db"


def _setting(name: str, default: str) -> str:
    process_value = os.getenv(name)
    if process_value is not None and process_value.strip():
        return process_value

    file_value = dotenv_values(_DOTENV_PATH).get(name)
    return file_value if file_value is not None else default


_DEV_SESSION_SECRET = "dev-only-insecure-secret"
_MIN_SESSION_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    session_secret: str
    admin_token: str


def load_settings() -> Settings:
    app_env = _setting("APP_ENV", "development").strip().lower()
    session_secret = _setting("SESSION_SECRET", _DEV_SESSION_SECRET)
    # Fail closed: only an explicit development env may use the known fallback.
    # Never include the supplied value in the error.
    if app_env != "development" and (
        session_secret == _DEV_SESSION_SECRET or len(session_secret) < _MIN_SESSION_SECRET_LENGTH
    ):
        raise RuntimeError(
            f"SESSION_SECRET must be set to a random value of at least "
            f"{_MIN_SESSION_SECRET_LENGTH} characters when APP_ENV={app_env!r}"
        )
    return Settings(
        app_env=app_env,
        database_url=_setting("DATABASE_URL", _DEFAULT_DATABASE_URL),
        session_secret=session_secret,
        admin_token=_setting("ADMIN_TOKEN", ""),
    )
