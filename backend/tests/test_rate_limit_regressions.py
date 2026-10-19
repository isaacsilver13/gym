from concurrent.futures import ThreadPoolExecutor

from app.api import auth
from app.rate_limit import RateLimiter, client_ip
from starlette.requests import Request


def test_capacity_is_bounded_and_recovers_after_expiry():
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0], max_keys=3)
    assert all(limiter.hit(str(i)) for i in range(3))
    assert not any(limiter.hit(str(i)) for i in range(3, 100))
    assert len(limiter._hits) == 3
    now[0] = 10.0
    assert limiter.hit("new")
    assert len(limiter._hits) == 1


def test_concurrent_admission_respects_limit():
    limiter = RateLimiter(5, 60)
    with ThreadPoolExecutor(max_workers=20) as pool:
        allowed = list(pool.map(lambda _: limiter.hit("one-client"), range(100)))
    assert sum(allowed) == 5


def test_proxy_identity_requires_explicit_fly_ingress(monkeypatch):
    monkeypatch.setattr("app.config.dotenv_values", lambda _p: {})
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("TRUST_FLY_CLIENT_IP", "true")
    request = Request({"type": "http", "client": ("127.0.0.1", 80),
                       "headers": [(b"fly-client-ip", b"203.0.113.5")]})
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    assert client_ip(request) == "127.0.0.1"
    monkeypatch.setenv("FLY_APP_NAME", "fixture-app")
    assert client_ip(request) == "203.0.113.5"


def test_missing_user_still_checks_a_password(client, monkeypatch):
    checked = []
    monkeypatch.setattr(
        auth, "verify_password", lambda password, hashed: checked.append(hashed) or False
    )
    response = client.post(
        "/api/v1/auth/login", json={"username": "absent", "password": "incorrect"}
    )
    assert response.status_code == 401
    assert checked == [auth._DUMMY_PASSWORD_HASH]
