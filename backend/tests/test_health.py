def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "healthy"


def test_health_metrics_before_any_activity(client):
    response = client.get("/api/v1/health/metrics")
    assert response.status_code == 200
    assert response.json()["sessions_logged_total"] == 0
    assert response.json()["last_activity_at"] is None
