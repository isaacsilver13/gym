# ruff: noqa: F811
import json
from datetime import date

import httpx
import pytest
from app.aisaac_sync import (
    DestinationDeleted,
    apple_uuid,
    send_cardio,
    send_strength,
    strength_workout,
    sync_once,
)
from app.apple_health import enqueue, retry_credentials, work_once
from app.apple_health_fit import normalize, to_fit
from app.training import TrainingSettings, lifting_activities, week_window

from .test_apple_health import cfg, decode, prepared, row, set_row, workout  # noqa: F401


def payload():
    return {
        "name": "Push",
        "start": "2026-10-27T12:00:00Z",
        "end": None,
        "exercises": [
            {
                "id": "1",
                "name": "Press",
                "sets": [{"weight_lb": 100, "reps_done": 8}, {"weight_lb": 90, "reps_done": 10}],
            }
        ],
    }


def test_strength_converts_units_and_preserves_only_explicit_sets():
    state = {"unit": "kg", "customEx": [{"id": "keep", "n": "Existing"}]}
    result = strength_workout(state, payload(), "owner:session:1", "digest")
    assert result["entries"][0]["sets"][0]["w"] == pytest.approx(45.359237)
    assert len(result["entries"][0]["sets"]) == 2 and "end" not in result
    state["workouts"] = [result]
    assert strength_workout(state, payload(), "owner:session:1", "digest") is None
    assert state["customEx"][0]["id"] == "keep"


def test_summary_only_counts_session_but_no_sets_and_deletion_blocks_replay():
    data = {**payload(), "exercises": []}
    result = strength_workout({}, data, "watch1", "digest")
    start, end = week_window(date(2026, 10, 27), "America/Chicago")
    activities = lifting_activities({"workouts": [result]}, start, end)
    assert (
        len(activities) == 1
        and activities[0]["summary_only"]
        and activities[0]["working_sets"] == 0
    )
    for state in (
        {"deleted": {"workouts": {result["id"]: 1}}},
        {"resetIds": {"workouts": [result["id"]]}},
    ):
        with pytest.raises(DestinationDeleted):
            strength_workout(state, data, "watch1", "digest")


def test_revision_conflict_refetches_and_preserves_concurrent_edit():
    cfg = TrainingSettings(
        username="alice",
        timezone="America/Chicago",
        opengym_public_url="",
        opengym_url="http://opengym-api:3000",
        opengym_uid="7",
        opengym_token="test",
    )
    writes = []

    def handler(request):
        if request.url.path == "/api/me":
            return httpx.Response(200, json={"user": {"id": 7}})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "rev": len(writes),
                    "state": {
                        "unit": "lb",
                        "workouts": [],
                        "routines": [{"name": "concurrent" if writes else "original"}],
                    },
                },
            )
        writes.append(json.loads(request.content))
        return httpx.Response(409 if len(writes) == 1 else 200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        send_strength(client, cfg, payload(), "owner:session:1", "digest")
    assert len(writes) == 2 and writes[1]["state"]["routines"] == [{"name": "concurrent"}]
    assert len(writes[1]["state"]["workouts"]) == 1


def test_same_apple_uuid_preserves_existing_richer_export(cfg, workout):
    enqueue(cfg, prepared(workout))
    original = row(cfg)
    summary = {
        k: v for k, v in workout.items() if k not in {"route", "heartRateData", "maxHeartRate"}
    }
    assert send_cardio(cfg, summary) == ("processing", None)
    assert row(cfg)["digest"] == original["digest"] and row(cfg)["fit"] == original["fit"]
    assert apple_uuid(workout["id"]) == workout["id"]
    assert apple_uuid("shortcut-id") == apple_uuid("shortcut-id")


def test_lost_response_and_credentials_repair_keep_original_key(cfg, workout):
    enqueue(cfg, prepared(workout))
    original = row(cfg)

    def lost(request):
        raise httpx.ReadTimeout("response lost")

    with httpx.Client(transport=httpx.MockTransport(lost)) as client:
        work_once(cfg, client, now=100)
    set_row(cfg, state="failed", error="upload_credential_rejected")
    retry_credentials(cfg, apply=True)
    workout["distance"]["qty"] = 10
    enqueue(cfg, prepared(workout))
    assert row(cfg)["digest"] == original["digest"] and row(cfg)["attempted"] == 1


@pytest.mark.parametrize(
    "name,sport,sub",
    [
        ("Outdoor Walk", "walking", "generic"),
        ("Indoor Cycle", "cycling", "indoor_cycling"),
        ("Pool Swim", "swimming", "lap_swimming"),
        ("Open Water Swim", "swimming", "open_water"),
        ("Hiking", "hiking", "generic"),
    ],
)
def test_cardio_fit_does_not_invent_distance(workout, name, sport, sub):
    workout["name"] = name
    workout.pop("distance")
    session = decode(to_fit(normalize(workout)))["session_mesgs"][0]
    assert session["sport"] == sport and session["sub_sport"] == sub
    assert "total_distance" not in session


def test_blank_owner_in_dotenv_falls_back_to_hub_username(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("AISAAC_OWNER=\n")  # a blank key must not mask the username fallback
    monkeypatch.setattr("app.config._DOTENV_PATH", dotenv)
    monkeypatch.delenv("AISAAC_OWNER", raising=False)
    for name, value in {
        "AISAAC_SYNC_URL": "https://aisaac.example",
        "AISAAC_SYNC_TOKEN": "t",
        "TRAINING_USERNAME": "alice",
    }.items():
        monkeypatch.setenv(name, value)
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"owner": "alice", "jobs": [], "weeks": []})

    sync_once(httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen == ["/api/v1/gym/sync/jobs", "/api/v1/gym/sync/weeks"]
