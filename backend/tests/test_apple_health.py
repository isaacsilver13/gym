import asyncio
import copy
import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from app.apple_health import AppleHealthSettings, connect, enqueue, queue_status, work_once
from app.apple_health_fit import InvalidWorkout, normalize, to_fit
from garmin_fit_sdk import FIT_EPOCH_S, Decoder, Stream


@pytest.fixture(autouse=True)
def idle_background_worker(monkeypatch):
    async def idle():
        await asyncio.sleep(3600)
    monkeypatch.setattr("app.main.worker", idle)


@pytest.fixture
def workout():
    return {"id": "50cccd8d-c34e-4b66-b1b3-012345678900", "name": "Running",
            "start": "2026-10-27 07:00:00 -0500", "end": "2026-10-27 07:30:00 -0500",
            "duration": 1500, "distance": {"qty": 3.1, "units": "mi"},
            "avgHeartRate": {"qty": 150, "units": "bpm"},
            "maxHeartRate": {"qty": 170, "units": "bpm"},
            "heartRateData": [{"date": "2026-10-27 07:00:00 -0500", "Avg": 140,
                               "Min": 130, "Max": 150, "units": "bpm"}],
            "route": [{"timestamp": "2026-10-27 07:00:00 -0500", "latitude": 0.0,
                       "longitude": 0.0, "altitude": 20, "speed": 3.3},
                      {"timestamp": "2026-10-27 07:30:00 -0500", "latitude": 0.01,
                       "longitude": 0.01, "altitude": 30, "speed": 3.4}]}


@pytest.fixture
def cfg(tmp_path):
    return AppleHealthSettings("alice", "http://endurain:8080", "7",
                               hashlib.sha256(b"phone-key").hexdigest(), "upload-only-key",
                               tmp_path / "outbox.sqlite")


def prepared(workout):
    normalized = normalize(workout)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return [(normalized["id"], hashlib.sha256(canonical.encode()).hexdigest(), to_fit(normalized))]


def decode(blob):
    messages, errors = Decoder(Stream.from_byte_array(blob)).read()
    assert not errors
    return messages


def test_fit_preserves_summary_timer_utc_hr_route(workout):
    messages = decode(to_fit(normalize(workout)))
    session = messages["session_mesgs"][0]
    assert session["total_elapsed_time"] == 1800
    assert session["total_timer_time"] == 1500
    assert session["total_distance"] == pytest.approx(4988.97, abs=0.01)
    assert session["avg_heart_rate"] == 150
    assert session["max_heart_rate"] == 170
    assert session["start_time"].hour == 12
    records = messages["record_mesgs"]
    assert len(records) == 2
    assert records[0]["heart_rate"] == 140
    assert records[0]["position_lat"] == 0
    assert all("distance" not in record for record in records)  # No interpolated splits.


def test_treadmill_without_samples_keeps_unknowns_and_local_offset(workout):
    for key in ("route", "heartRateData", "avgHeartRate", "maxHeartRate"):
        workout.pop(key)
    workout["start"] = "2026-10-27 07:00:00 +0900"
    workout["end"] = "2026-10-27 07:30:00 +0900"
    workout["isIndoor"] = True
    messages = decode(to_fit(normalize(workout)))
    assert not messages.get("record_mesgs")
    session = messages["session_mesgs"][0]
    assert session["sub_sport"] == "treadmill"
    assert "avg_heart_rate" not in session
    assert session["total_timer_time"] == 1500
    activity = messages["activity_mesgs"][0]
    utc_fit_seconds = activity["timestamp"].timestamp() - FIT_EPOCH_S
    assert activity["local_timestamp"] - utc_fit_seconds == 9 * 3600


@pytest.mark.parametrize("name", ["Outdoor Run", "Indoor Run"])
def test_health_auto_export_run_names_are_imported(workout, name):
    workout["name"] = name  # "Outdoor Run" is what Health Auto Export v2 actually sends
    assert normalize(workout) is not None


def test_health_auto_export_heart_rate_uses_count_per_minute(workout):
    # Real Health Auto Export v2 labels every heart-rate quantity "count/min", not "bpm".
    workout["avgHeartRate"]["units"] = workout["maxHeartRate"]["units"] = "count/min"
    workout["heartRateData"][0]["units"] = "count/min"
    result = normalize(workout)
    assert (result["avg_hr"], result["max_hr"]) == (150, 170)
    assert result["records"][0]["heart_rate"] == 140


def test_minute_bucketed_heart_rate_just_outside_the_workout_is_snapped_to_it(workout):
    # Minute grouping dates the first bucket before the workout starts (seen: 34 s early).
    workout["heartRateData"] = [
        {"date": "2026-10-27 06:59:26 -0500", "Avg": 120, "units": "count/min"},  # 34 s early
        {"date": "2026-10-27 07:30:40 -0500", "Avg": 130, "units": "count/min"}]  # 40 s late
    times = [r["time"] for r in normalize(workout)["records"] if "heart_rate" in r]
    start = normalize(workout)["start"]
    assert times == [start, start + 1800]
    workout["heartRateData"][0]["date"] = "2026-10-27 06:58:00 -0500"  # 2 min early: still bad
    with pytest.raises(InvalidWorkout):
        normalize(workout)


def test_missing_distance_requires_attention(workout):
    workout.pop("distance")
    with pytest.raises(InvalidWorkout, match="requires recorded distance"):
        normalize(workout)


@pytest.mark.parametrize("change", [
    {"id": "not-a-uuid"}, {"start": "2026-10-27 07:00:00"}, {"duration": 2000},
    {"duration": float("nan")}, {"distance": {"qty": -1, "units": "mi"}},
    {"distance": {"qty": 5, "units": "yards"}},
    {"route": [{"timestamp": "2026-10-27 07:00:00 -0500", "latitude": 91, "longitude": 0}]},
    {"heartRateData": [{"date": "2026-10-28 07:00:00 -0500", "Avg": 140, "units": "bpm"}]},
])
def test_rejects_bad_values(workout, change):
    workout.update(change)
    with pytest.raises(InvalidWorkout):
        normalize(workout)


def test_worker_persists_job_before_poll_and_replays_do_not_upload(cfg, workout):
    item = prepared(workout)
    assert enqueue(cfg, item)["queued"] == 1
    job_id = str(uuid4())
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-API-Key"] == "upload-only-key"
        if request.method == "POST":
            assert request.headers["Idempotency-Key"].startswith("apple-health-v1:")
            return httpx.Response(202, json={"id": job_id, "status": "pending"})
        assert request.url.path.endswith(job_id)
        return httpx.Response(200, json={"id": job_id, "status": "completed", "activity_ids": [42]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert work_once(cfg, client, now=100)
        assert queue_status(cfg)["counts"] == {"processing": 1}
        # Simulated restart: a fresh call reads the saved job ID instead of posting.
        assert work_once(cfg, client, now=103)
        assert enqueue(cfg, item)["duplicates"] == 1
        assert not work_once(cfg, client, now=106)
    assert [r.method for r in calls] == ["POST", "GET"]
    assert queue_status(cfg)["recent"][0]["activity_ids"] == [42]
    with __import__("sqlite3").connect(cfg.queue) as db:
        assert db.execute("SELECT fit FROM workouts").fetchone()[0] is None


def test_transient_retry_stable_key_and_changed_export(cfg, workout):
    enqueue(cfg, prepared(workout))
    keys = []

    def handler(request):
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert work_once(cfg, client, now=100)
        assert not work_once(cfg, client, now=101)
        assert work_once(cfg, client, now=161)
    assert keys[0] == keys[1]
    workout["distance"]["qty"] = 4
    assert enqueue(cfg, prepared(workout)) == {"queued": 0, "duplicates": 1, "changed": 1}
    assert queue_status(cfg)["changed"] == 1
    with pytest.raises(ValueError, match="another account"):
        queue_status(replace(cfg, endurain_user_id="8"))


def test_replaced_export_uses_a_new_idempotency_key(cfg, workout):
    # Endurain returns 409 when a known key arrives with a different file.
    keys = []

    def handler(request):
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        enqueue(cfg, prepared(workout))
        assert work_once(cfg, client, now=100)
        with connect(cfg) as db:  # operator clears the entry to replace the import
            db.execute("DELETE FROM workouts")
        workout["distance"]["qty"] = 4
        enqueue(cfg, prepared(workout))
        assert work_once(cfg, client, now=200)
    assert keys[0] != keys[1]


def test_terminal_rejection_does_not_retry_or_leak_response(cfg, workout):
    enqueue(cfg, prepared(workout))
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
            403, json={"secret": "PRIVATE"}))) as client:
        work_once(cfg, client, now=100)
        assert not work_once(cfg, client, now=10000)
    result = queue_status(cfg)
    assert result["counts"] == {"failed": 1}
    assert result["recent"][0]["error"] == "upload_credential_rejected"
    assert "PRIVATE" not in json.dumps(result)


@pytest.fixture
def configured(monkeypatch, cfg):
    monkeypatch.setattr(AppleHealthSettings, "load", classmethod(lambda cls: cfg))
    # Worker behavior tested synchronously; prevent test lifespan racing assertions.
    from app.api.apple_health import limiter
    limiter._hits.clear()
    return cfg


def test_receiver_auth_validation_dedupe_and_status(auth_client, configured, workout):
    endpoint = "/api/v1/integrations/apple-health/workouts"
    headers = {"Authorization": "Bearer phone-key"}
    payload = {"data": {"workouts": [workout, {"name": "Traditional Strength Training"}]}}
    assert auth_client.post(endpoint, json=payload).status_code == 401
    response = auth_client.post(endpoint, json=payload, headers=headers)
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    assert response.json()["skipped_non_running"] == 1
    assert auth_client.post(endpoint, json=payload, headers=headers).json()["duplicates"] == 1
    status = auth_client.get("/api/v1/training/apple-health")
    assert status.status_code == 200
    assert status.json()["configured"]
    assert "route" not in status.text and "upload-only-key" not in status.text


def test_rejects_entire_invalid_batch_and_large_body(client, configured, workout, monkeypatch):
    endpoint = "/api/v1/integrations/apple-health/workouts"
    headers = {"Authorization": "Bearer phone-key"}
    bad = copy.deepcopy(workout)
    bad["id"] = "BROKEN-PRIVATE-ID"
    response = client.post(endpoint, json={"data": {"workouts": [workout, bad]}}, headers=headers)
    assert response.status_code == 422
    assert "BROKEN-PRIVATE-ID" not in response.text
    assert queue_status(configured)["counts"] == {}
    monkeypatch.setattr("app.api.apple_health.MAX_BODY", 10)
    assert client.post(endpoint, json={"data": {"workouts": [workout]}},
                       headers=headers).status_code == 413


def test_other_owner_cannot_read_status(client, configured):
    client.post("/api/v1/auth/register", json={"username": "bob", "password": "correct-horse"})
    assert client.get("/api/v1/training/apple-health").status_code == 403


def test_disabled_and_bad_configuration(client, monkeypatch):
    monkeypatch.setattr(AppleHealthSettings, "load", classmethod(lambda cls: None))
    assert client.post("/api/v1/integrations/apple-health/workouts").status_code == 404
    def bad(cls):
        raise ValueError("PRIVATE configuration error")
    monkeypatch.setattr(AppleHealthSettings, "load", classmethod(bad))
    response = client.post("/api/v1/integrations/apple-health/workouts")
    assert response.status_code == 503
    assert "PRIVATE" not in response.text


def test_configuration_checks_exact_mapping(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"format": 1, "owner": "alice", "endurain_url": "http://localhost:8080",
                                "endurain_user_id": "7", "token_sha256": "a" * 64,
                                "upload_key": "secret"}))
    monkeypatch.setenv("APPLE_HEALTH_CONFIG_FILE", str(path))
    monkeypatch.setenv("TRAINING_USERNAME", "alice")
    monkeypatch.setenv("ENDURAIN_URL", "http://localhost:8080")
    monkeypatch.setenv("ENDURAIN_USER_ID", "7")
    assert AppleHealthSettings.load().owner == "alice"
    monkeypatch.setenv("ENDURAIN_USER_ID", "8")
    with pytest.raises(ValueError):
        AppleHealthSettings.load()


def test_worker_recovers_after_malformed_configuration(monkeypatch, tmp_path):
    from app.apple_health import worker
    path = tmp_path / "config.json"
    path.write_text("[]")
    monkeypatch.setenv("APPLE_HEALTH_CONFIG_FILE", str(path))
    calls = []

    async def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 1:
            path.write_text('{"token_sha256": null}')
        else:
            monkeypatch.setenv("APPLE_HEALTH_CONFIG_FILE", "")
            raise asyncio.CancelledError

    monkeypatch.setattr("app.apple_health.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker())
    assert len(calls) == 2


def test_setup_keeps_server_credential_off_phone_and_refuses_overwrite(tmp_path):
    from app.apple_health_setup import ENDPOINT, save_connection
    config, phone = tmp_path / "config.json", tmp_path / "phone.json"
    values = dict(owner="alice", base="http://localhost:8080", user_id="7",
                  upload_key="server-only-key", receiver="https://example.ts.net" + ENDPOINT)
    save_connection(config, phone, **values)
    server, mobile = json.loads(config.read_text()), json.loads(phone.read_text())
    token = mobile["headers"]["Authorization"][7:]
    assert server["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in config.read_text()
    assert "server-only-key" not in phone.read_text()
    with pytest.raises(ValueError, match="not be overwritten"):
        save_connection(config, phone, **values)
