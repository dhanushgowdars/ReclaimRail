from fastapi.testclient import TestClient

from app.main import app


def test_live_health_returns_service_metadata() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "reclaimrail-api",
        "version": "0.1.0",
    }
