import hashlib
import json

import pytest
from app.migration import plan_from_export, write_bundle

from tests.test_routines import _routine_payload


def test_owner_export_preserves_summaries_and_excludes_auth(auth_client):
    routine = auth_client.post("/api/v1/routines", json=_routine_payload()).json()
    day = routine["gym_days"][0]
    auth_client.post(f"/api/v1/routines/{routine['id']}/sessions", json={
        "gym_day_id": day["id"], "results": [{
            "exercise_definition_id": day["exercises"][0]["id"],
            "weight_lb": 185, "reps_done": 8,
        }],
    })
    exported = auth_client.get("/api/v1/training/legacy-export").json()
    plan, report = plan_from_export(exported)
    assert exported["sessions"][0]["results"][0]["reps_done"] == 8
    assert report["legacy_results_preserved"] == 1
    assert report["completed_sets_inferred"] == 0
    assert "workouts" not in plan
    assert plan["unit"] == "lb" and len(plan["routines"]) == 2
    assert plan["routines"][0]["ex"][0]["sets"] == 4
    assert all(e["prog"] == "off" for r in plan["routines"] for e in r["ex"])
    assert "password" not in json.dumps(exported)
    auth_client.post("/api/v1/auth/logout")
    auth_client.post("/api/v1/auth/register", json={"username": "bob", "password": "safe-password"})
    other = auth_client.get("/api/v1/training/legacy-export").json()
    assert other["routines"] == [] and other["sessions"] == []


def test_export_checksums_repeat_safety_and_conflict(tmp_path):
    data = {"format": "gym-legacy-v1", "unit": "lb", "routines": [], "sessions": []}
    out = tmp_path / "export"
    write_bundle(data, out)
    write_bundle(data, out)
    manifest = json.loads((out / "manifest.json").read_text())
    for name, sha in manifest["sha256"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == sha
    with pytest.raises(FileExistsError):
        write_bundle({**data, "owner": {"username": "different"}}, out)
