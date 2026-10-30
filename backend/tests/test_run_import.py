import httpx
import pytest
from app.run_import import bind_manifest, import_file, poll_job


def test_manifest_is_bound_to_one_server_and_credential():
    manifest = {"url": "https://runs.test", "files": {}}
    bind_manifest(manifest, "https://runs.test", "key-alice")
    bind_manifest(manifest, "https://runs.test", "key-alice")
    with pytest.raises(ValueError):
        bind_manifest(manifest, "https://runs.test", "key-bob")
    with pytest.raises(ValueError):
        bind_manifest(manifest, "https://another.test", "key-alice")
    assert "key-alice" not in str(manifest)


def test_upload_uses_pinned_route_key_and_resumes_job(tmp_path):
    path = tmp_path / "watch.fit"
    path.write_bytes(b"synthetic-test-payload")
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            assert request.url.path == "/api/v1/activities/upload"
            assert request.headers["X-API-Key"] == "upload-secret"
            assert request.headers["Idempotency-Key"].startswith("training-hub:")
            return httpx.Response(202, json={"id": "job-1", "status": "queued"})
        assert request.url.path == "/api/v1/activities/ingestion-jobs/job-1"
        return httpx.Response(200, json={"id": "job-1", "status": "completed",
                                        "activity_ids": [42]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = import_file(client, "http://localhost:18082", "upload-secret", path)
        resumed = import_file(client, "http://localhost:18082", "upload-secret", path, first)
        assert resumed == first and len(requests) == 1
        done = poll_job(client, "http://localhost:18082", "upload-secret", resumed)
        assert done["activity_ids"] == [42]
        assert import_file(client, "http://localhost:18082", "upload-secret", path, done) == done
        assert len(requests) == 2
