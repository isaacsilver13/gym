import pytest
from app.db import Base, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(client):
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "correct-horse"})
    return client


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    from app.api import auth as auth_routes

    for limiter in (
        auth_routes.login_ip_limiter,
        auth_routes.login_user_limiter,
        auth_routes.register_limiter,
    ):
        limiter._hits.clear()
