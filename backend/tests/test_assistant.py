from datetime import UTC, datetime, timedelta

import pytest
from app.db import get_db
from app.main import app
from app.models import LoggedSession

from tests.test_routines import _routine_payload

URL = "/api/v1/assistant/summary"
TOKEN = "assistant-secret"
HEADERS = {"X-Assistant-Token": TOKEN}


@pytest.fixture()
def assistant_env(monkeypatch):
    monkeypatch.setenv("ASSISTANT_READ_TOKEN", TOKEN)
    monkeypatch.setenv("ASSISTANT_USERNAME", "alice")


def _log(client, routine, day_index, results):
    day = routine["gym_days"][day_index]
    ids = [exercise["id"] for exercise in day["exercises"]]
    response = client.post(
        f"/api/v1/routines/{routine['id']}/sessions",
        json={
            "gym_day_id": day["id"],
            "results": [
                {"exercise_definition_id": i, "weight_lb": w, "reps_done": r}
                for i, (w, r) in zip(ids, results, strict=True)
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize("unset", ["ASSISTANT_READ_TOKEN", "ASSISTANT_USERNAME"])
def test_disabled_when_unset(auth_client, assistant_env, monkeypatch, unset):
    monkeypatch.delenv(unset)
    assert auth_client.get(URL, headers=HEADERS).status_code == 404


def test_wrong_or_missing_token_forbidden(auth_client, assistant_env):
    assert auth_client.get(URL, headers={"X-Assistant-Token": "wrong"}).status_code == 403
    assert auth_client.get(URL).status_code == 403


def test_no_routine(auth_client, assistant_env):
    body = auth_client.get(URL, headers=HEADERS).json()
    assert body["username"] == "alice"
    assert body["routine"] is None and body["next_gym_day"] is None


def test_no_sessions_starts_at_day_one(auth_client, assistant_env):
    routine = auth_client.post("/api/v1/routines", json=_routine_payload()).json()
    body = auth_client.get(URL, headers=HEADERS).json()
    assert body["routine"]["id"] == routine["id"]
    assert body["next_gym_day"]["id"] == routine["gym_days"][0]["id"]
    assert body["last_session_date"] is None
    assert [e["name"] for e in body["exercises"]] == ["Bench Press", "Overhead Press", "Deadlift"]
    assert all(e["latest"] is None and e["best_30d"] is None for e in body["exercises"])


def test_rotation_advances_and_wraps(auth_client, assistant_env):
    routine = auth_client.post("/api/v1/routines", json=_routine_payload()).json()
    _log(auth_client, routine, 0, [(185, 8), (95, 10)])
    body = auth_client.get(URL, headers=HEADERS).json()
    assert body["next_gym_day"]["id"] == routine["gym_days"][1]["id"]

    _log(auth_client, routine, 1, [(315, 5)])
    body = auth_client.get(URL, headers=HEADERS).json()
    assert body["next_gym_day"]["id"] == routine["gym_days"][0]["id"]
    assert body["last_session_date"] == datetime.now(UTC).date().isoformat()


def test_prefers_trained_routine_over_newer_untrained(auth_client, assistant_env):
    trained = auth_client.post("/api/v1/routines", json=_routine_payload()).json()
    _log(auth_client, trained, 0, [(185, 8), (95, 10)])
    auth_client.post("/api/v1/routines", json={**_routine_payload(), "name": "New"})
    assert auth_client.get(URL, headers=HEADERS).json()["routine"]["id"] == trained["id"]


def test_best_set_tie_break_and_window(auth_client, assistant_env):
    routine = auth_client.post("/api/v1/routines", json=_routine_payload()).json()
    old = _log(auth_client, routine, 0, [(300, 1), (95, 10)])
    _log(auth_client, routine, 0, [(185, 8), (95, 10)])
    _log(auth_client, routine, 0, [(185, 10), (95, 10)])
    _log(auth_client, routine, 0, [(175, 12), (95, 10)])

    # Push the 300 lb session outside the 30-day window.
    db = next(app.dependency_overrides[get_db]())
    db.get(LoggedSession, old["id"]).logged_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()

    bench = auth_client.get(URL, headers=HEADERS).json()["exercises"][0]
    assert (bench["best_30d"]["weight_lb"], bench["best_30d"]["reps_done"]) == (185, 10)
    assert (bench["latest"]["weight_lb"], bench["latest"]["reps_done"]) == (175, 12)
