from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes import health
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


def test_ready_health_returns_ready_when_dependencies_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "check_database", AsyncMock(return_value=None))
    monkeypatch.setattr(health, "check_redis", AsyncMock(return_value=None))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "up"
    assert body["checks"]["redis"]["status"] == "up"


def test_ready_health_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "check_database",
        AsyncMock(side_effect=ConnectionError("Database unavailable")),
    )
    monkeypatch.setattr(health, "check_redis", AsyncMock(return_value=None))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    body = response.json()

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "down"
    assert body["checks"]["redis"]["status"] == "up"
    assert "Database unavailable" not in response.text
