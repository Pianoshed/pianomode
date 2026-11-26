from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_reports_database(client: TestClient) -> None:
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok"
