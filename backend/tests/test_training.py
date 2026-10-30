import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest
from app.training import (
    TrainingSettings,
    build_summary,
    lifting_activities,
    running_activities,
    safe_url,
    week_window,
)
from app.training_tokens import save_tokens


@pytest.fixture()
def cfg(tmp_path):
    path = tmp_path / "endurain.json"
    save_tokens(path, "http://localhost:18082", {
        "access_token": "access-secret", "refresh_token": "refresh-secret",
    })
    return TrainingSettings("alice", "America/Chicago", "http://localhost:18081",
                            "http://localhost:18081", "gym-alice", "gym-secret",
                            "http://localhost:18082", "http://localhost:18082", "7", str(path))


def workout(**extra):
    return {"id": "w1", "d": "2026-10-27", "name": "Push",
            "entries": [{"id": "bench", "sets": [
                {"r": 8, "w": 100, "done": True, "phase": "warmup"},
                {"r": 8, "w": 185, "done": True},
                {"r": 8, "w": 185, "done": False},
            ]}], **extra}


def run(**extra):
    return {"id": 1, "user_id": 7, "name": "Easy run", "activity_type": 1,
            "start_time": "2026-10-27T12:00:00Z", "distance": 5000,
            "total_timer_time": 1800, "total_elapsed_time": 2000,
            "average_hr": 145, **extra}


def test_actual_upstream_envelopes_and_credentials(cfg):
    def handler(request):
        if request.url.path == "/api/me":
            assert request.headers["Authorization"] == "Bearer gym-secret"
            return httpx.Response(200, json={"user": {"id": "gym-alice"}})
        if request.url.path == "/api/data":
            return httpx.Response(200, json={"state": {"workouts": [workout()]}, "rev": 2})
        assert request.headers["Authorization"] == "Bearer access-secret"
        assert request.headers["X-Client-Type"] == "mobile"
        return httpx.Response(200, json={"items": [run()], "total": 1})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body = build_summary(cfg, date(2026, 10, 27), client)
    assert body["totals"]["lifting_sessions"] == 1
    assert body["totals"]["working_sets"] == 1
    assert body["totals"]["running_distance_meters"] == 5000
    running = next(a for a in body["activities"] if a["sport"] == "running")
    assert running["pace_seconds_per_km"] == 360
    rendered = json.dumps(body)
    assert "secret" not in rendered and "city" not in rendered


def test_unilateral_completions_match_upstream_units():
    start, end = week_window(date(2026, 10, 27), "America/Chicago")
    for sides, expected in [({"L": {"r": 8, "done": True}, "R": {"r": 8}}, 1),
                            ({"L": {"r": 8, "done": True},
                              "R": {"r": 8, "done": True}}, 2)]:
        w = workout(entries=[{"id": "row", "sets": [{"sides": sides}]}])
        assert lifting_activities({"workouts": [w]}, start, end)[0]["working_sets"] == expected


def test_profile_mismatch_fails_closed(cfg):
    def handler(request):
        if request.url.path == "/api/me":
            return httpx.Response(200, json={"user": {"id": "someone-else"}})
        return httpx.Response(200, json={"items": [run(user_id=999)], "total": 1})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body = build_summary(cfg, date(2026, 10, 27), client)
    assert all(s["state"] == "unavailable" for s in body["sources"].values())
    assert body["activities"] == []
    assert body["totals"]["runs"] is None


def test_missing_sources_are_not_zero(cfg):
    body = build_summary(replace(cfg, opengym_token="", endurain_token_file=""))
    assert body["totals"]["lifting_sessions"] is None
    assert body["totals"]["running_distance_meters"] is None


def test_running_filter_units_duplicates_and_missing_data():
    start, end = week_window(date(2026, 10, 27), "America/Chicago")
    rows = [run(), run(), run(id=2, activity_type=19), run(id=3, is_hidden=True),
            run(id=4, activity_type=40, total_timer_time=None, average_hr=None),
            run(id=5, start_time="2026-10-26T01:00:00Z")]
    actual = running_activities(rows, "7", start, end)
    assert len(actual) == 2
    assert actual[0]["pace_seconds_per_km"] == 360
    assert actual[1]["duration_seconds"] is None
    assert actual[1]["average_heart_rate"] is None
    assert actual[1]["pace_seconds_per_km"] is None


def test_dst_calendar_week_is_not_fixed_168_hours():
    start, end = week_window(date(2026, 11, 1), "America/Chicago")
    assert end.timestamp() - start.timestamp() == 169 * 3600


def test_running_pagination_and_refresh(cfg):
    refreshed = False
    def handler(request):
        nonlocal refreshed
        if request.url.path == "/api/v1/auth/refresh":
            assert request.headers["Authorization"] == "Bearer refresh-secret"
            refreshed = True
            return httpx.Response(200, json={"access_token": "new-access",
                                            "refresh_token": "new-refresh"})
        if request.url.path.startswith("/api/") and request.url.path != "/api/v1/activities":
            return httpx.Response(503)
        if not refreshed:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer new-access"
        page = int(request.url.params["page_number"])
        return httpx.Response(200, json={"items": [run(id=page)], "total": 2})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body = build_summary(cfg, date(2026, 10, 27), client)
    assert body["totals"]["runs"] == 2
    stored = json.loads(Path(cfg.endurain_token_file).read_text())
    assert stored["refresh_token"] == "new-refresh"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:pass@example.com",
                                "https://example.com?token=secret", "http://example.com"])
def test_url_validation(url):
    with pytest.raises(ValueError):
        safe_url(url)


def test_hub_auth_and_owner_isolation(auth_client, monkeypatch):
    monkeypatch.setenv("TRAINING_USERNAME", "another-user")
    assert auth_client.get("/api/v1/training/summary").status_code == 403
    monkeypatch.setenv("TRAINING_USERNAME", "alice")
    monkeypatch.setenv("OPENGYM_URL", "")
    monkeypatch.setenv("ENDURAIN_URL", "")
    assert auth_client.get("/api/v1/training/summary").status_code == 200
    assert auth_client.get("/api/v1/assistant/training").status_code == 404
    auth_client.post("/api/v1/auth/logout")
    assert auth_client.get("/api/v1/training/summary").status_code == 401
    assert auth_client.get("/api/v1/training/legacy-export").status_code == 401
