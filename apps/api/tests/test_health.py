from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import health
from app.core.database import get_database_session
from app.main import app
from app.services.operational_queue_service import (
    DatabaseQueueMetric,
    OperationalQueueDiagnostics,
    OperationalQueueStatus,
)
from app.services.worker_supervision_service import (
    EXPECTED_WORKERS,
    WorkerFleetHealth,
    WorkerFleetStatus,
    WorkerHealth,
    WorkerHealthStatus,
)


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


def build_worker_health() -> WorkerHealth:
    now = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)
    return WorkerHealth(
        name=EXPECTED_WORKERS[0],
        status=WorkerHealthStatus.HEALTHY,
        instance_id="outbox:test-host:42",
        heartbeat_age_seconds=0.5,
        started_at=now,
        last_heartbeat_at=now,
        last_success_at=now,
        last_failure_at=None,
        consecutive_failures=0,
        last_error_type=None,
        metrics={"published": 1},
    )


def test_worker_health_exposes_degraded_fleet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)
    fleet = WorkerFleetHealth(
        status=WorkerFleetStatus.DEGRADED,
        workers=(build_worker_health(),),
        healthy_count=1,
        expected_count=8,
        generated_at=now,
    )
    monkeypatch.setattr(health, "utc_now", MagicMock(return_value=now))
    monkeypatch.setattr(health, "get_redis_client", MagicMock(return_value=object()))
    monkeypatch.setattr(
        health,
        "load_worker_fleet_health",
        AsyncMock(return_value=fleet),
    )

    with TestClient(app) as client:
        response = client.get("/health/workers")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["healthy_count"] == 1
    assert body["expected_count"] == 8
    assert body["workers"][0]["name"] == "outbox"


def test_worker_health_hides_redis_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "get_redis_client",
        MagicMock(side_effect=ConnectionError("secret redis endpoint")),
    )

    with TestClient(app) as client:
        response = client.get("/health/workers")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["expected_count"] == 8
    assert "secret redis endpoint" not in response.text


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield AsyncMock(spec=AsyncSession)


def test_queue_health_exposes_pending_and_dead_letter_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)
    diagnostics = OperationalQueueDiagnostics(
        status=OperationalQueueStatus.ATTENTION_REQUIRED,
        database_queues=(
            DatabaseQueueMetric(
                name="recovery_actions",
                pending_count=2,
                oldest_age_seconds=4.5,
            ),
        ),
        webhook_stream_depth=10,
        payment_consumer_pending=1,
        dead_letter_depth=1,
        generated_at=now,
    )
    monkeypatch.setattr(health, "utc_now", MagicMock(return_value=now))
    monkeypatch.setattr(health, "get_redis_client", MagicMock(return_value=object()))
    monkeypatch.setattr(
        health,
        "load_operational_queue_diagnostics",
        AsyncMock(return_value=diagnostics),
    )
    app.dependency_overrides[get_database_session] = override_database_session
    try:
        with TestClient(app) as client:
            response = client.get("/health/queues")
    finally:
        app.dependency_overrides.pop(get_database_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "attention_required"
    assert body["database_queues"][0]["pending_count"] == 2
    assert body["payment_consumer_pending"] == 1
    assert body["dead_letter_depth"] == 1
