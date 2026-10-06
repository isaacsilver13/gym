import logging

import pytest
from app import error_log
from app.api import auth as auth_routes
from app.config import load_settings
from app.rate_limit import RateLimiter

STRONG = "x" * 40


def _env(monkeypatch, app_env, secret=None):
    monkeypatch.setenv("APP_ENV", app_env)
    if secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", secret)
    # keep a local .env from supplying a secret
    monkeypatch.setattr("app.config.dotenv_values", lambda _p: {})


def test_development_allows_fallback_secret(monkeypatch):
    _env(monkeypatch, "development")
    assert load_settings().session_secret == "dev-only-insecure-secret"


@pytest.mark.parametrize("secret", [None, "dev-only-insecure-secret", "short-secret"])
def test_production_rejects_missing_known_or_short_secret(monkeypatch, secret):
    _env(monkeypatch, "production", secret)
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    assert "short-secret" not in str(exc.value)


def test_production_accepts_strong_secret(monkeypatch):
    _env(monkeypatch, "production", STRONG)
    assert load_settings().session_secret == STRONG


def test_cookie_secure_outside_development(client, monkeypatch):
    from dataclasses import replace

    from app import auth

    monkeypatch.setattr(auth, "_settings", replace(auth._settings, app_env="production"))
    response = client.post(
        "/api/v1/auth/register", json={"username": "bob", "password": "correct-horse"}
    )
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie


def test_rate_limiter_window():
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.hit("a") and limiter.hit("a")
    assert not limiter.hit("a")
    assert limiter.hit("b")
    now[0] = 10.0
    assert limiter.hit("a")


def test_login_rate_limited_but_same_invalid_response(client):
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "correct-horse"})
    client.post("/api/v1/auth/logout")
    body = {"username": "alice", "password": "wrong-password"}
    for _ in range(auth_routes.login_user_limiter.limit):
        r = client.post("/api/v1/auth/login", json=body)
        assert r.status_code == 401
        assert r.json() == {"detail": "Invalid username or password"}
    r = client.post("/api/v1/auth/login", json=body)
    assert r.status_code == 429
    assert "alice" not in r.text


def test_register_rate_limited(client):
    for i in range(auth_routes.register_limiter.limit):
        assert (
            client.post(
                "/api/v1/auth/register", json={"username": f"user{i}", "password": "correct-horse"}
            ).status_code
            == 201
        )
    extra = {"username": "extra", "password": "correct-horse"}
    r = client.post("/api/v1/auth/register", json=extra)
    assert r.status_code == 429


def test_error_messages_are_redacted():
    msg = (
        "boom postgresql://user:hunter2@db.internal/app?sslmode=require "
        "password=hunter2 Authorization: Bearer abc.def\nTraceback line"
    )
    out = error_log.sanitize_message(msg)
    assert "hunter2" not in out and "abc.def" not in out and "Traceback" not in out


def test_redaction_json_and_basic_auth():
    out = error_log.sanitize_message(
        """body {"password": "hunter2", 'token': 'abc123'} Authorization: Basic dXNlcjpwYXNz"""
    )
    assert "hunter2" not in out and "abc123" not in out and "dXNlcjpwYXNz" not in out


def test_login_lockout_is_per_client(client):
    body = {"username": "alice", "password": "wrong-password"}
    for _ in range(auth_routes.login_user_limiter.limit):
        client.post("/api/v1/auth/login", json=body)
    assert client.post("/api/v1/auth/login", json=body).status_code == 429
    other = client.post("/api/v1/auth/login", json=body, headers={"fly-client-ip": "9.9.9.9"})
    assert other.status_code == 401


def test_health_errors_requires_admin_token(client, monkeypatch):
    error_log._recent_errors.clear()
    handler = error_log.RingBufferHandler(level=logging.ERROR)
    log = logging.getLogger("t")
    log.addHandler(handler)
    log.error("db failed token=SECRETVALUE")
    log.removeHandler(handler)

    assert client.get("/api/v1/health/errors").status_code == 403  # no ADMIN_TOKEN configured
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")
    assert client.get("/api/v1/health/errors").status_code == 403
    assert (
        client.get("/api/v1/health/errors", headers={"X-Admin-Token": "wrong"}).status_code == 403
    )
    ok = client.get("/api/v1/health/errors", headers={"X-Admin-Token": "admin-secret"})
    assert ok.status_code == 200
    assert "SECRETVALUE" not in ok.text
    error_log._recent_errors.clear()


def test_liveness_and_readiness_stay_public(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/ready").status_code == 200
