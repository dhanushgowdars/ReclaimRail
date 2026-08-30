from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_incidents
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.db.models.incident import RevenueIncident
from app.domain.incidents import IncidentSeverity
from app.main import app
from app.services.recovery_incident_feed_service import RecoveryIncidentFeedItem

INCIDENT_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def database_session_override() -> AsyncIterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session

    yield

    app.dependency_overrides.clear()


def drill_settings(*, enabled: bool = True, app_env: str = "test") -> Settings:
    return Settings(
        app_env=app_env,
        payment_lab_access_token="lab-secret",
        incident_test_drill_enabled=enabled,
    )


def build_incident() -> RecoveryIncidentFeedItem:
    return RecoveryIncidentFeedItem(
        incident_id=INCIDENT_ID,
        status="open",
        severity="high",
        scope="payment_method",
        dimension_value="upi",
        currency="INR",
        revenue_at_risk_minor=725_000,
        failure_rate=0.34,
        baseline_failure_rate=0.03,
        absolute_uplift=0.31,
        rate_multiplier=11.33,
        confidence=0.98,
        occurrence_count=3,
        reason_codes=("failure_rate_spike",),
        first_detected_at=NOW,
        last_detected_at=NOW,
    )


def test_lists_pii_safe_active_incidents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_incidents = AsyncMock(return_value=(build_incident(),))
    monkeypatch.setattr(
        recovery_incidents,
        "load_active_recovery_incidents",
        load_incidents,
    )

    with TestClient(app) as client:
        response = client.get("/recovery/dashboard/incidents")

    assert response.status_code == 200
    assert response.json() == [
        {
            "incident_id": str(INCIDENT_ID),
            "status": "open",
            "severity": "high",
            "scope": "payment_method",
            "dimension_value": "upi",
            "currency": "INR",
            "revenue_at_risk_minor": 725_000,
            "failure_rate": 0.34,
            "baseline_failure_rate": 0.03,
            "absolute_uplift": 0.31,
            "rate_multiplier": 11.33,
            "confidence": 0.98,
            "occurrence_count": 3,
            "reason_codes": ["failure_rate_spike"],
            "first_detected_at": "2026-08-26T07:00:00Z",
            "last_detected_at": "2026-08-26T07:00:00Z",
        },
    ]
    assert "email" not in response.text
    assert "contact" not in response.text
    assert load_incidents.await_args.kwargs == {
        "currency": "INR",
        "limit": 5,
    }


def test_accepts_currency_and_limit_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_incidents = AsyncMock(return_value=())
    monkeypatch.setattr(
        recovery_incidents,
        "load_active_recovery_incidents",
        load_incidents,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/incidents",
            params={"currency": "usd", "limit": "10"},
        )

    assert response.status_code == 200
    assert response.json() == []
    assert load_incidents.await_args.kwargs == {
        "currency": "usd",
        "limit": 10,
    }


def test_rejects_invalid_incident_limit_before_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_incidents = AsyncMock()
    monkeypatch.setattr(
        recovery_incidents,
        "load_active_recovery_incidents",
        load_incidents,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/incidents",
            params={"limit": "26"},
        )

    assert response.status_code == 422
    load_incidents.assert_not_awaited()


def test_starts_explicit_test_mode_incident_drill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = MagicMock(spec=RevenueIncident)
    incident.id = INCIDENT_ID
    incident.current_window_end = datetime(2026, 8, 26, 7, 10, tzinfo=UTC)
    create_drill = AsyncMock(return_value=incident)
    monkeypatch.setattr(
        recovery_incidents,
        "create_test_mode_incident_drill",
        create_drill,
    )
    app.dependency_overrides[get_settings] = lambda: drill_settings()

    with TestClient(app) as client:
        response = client.post(
            "/recovery/dashboard/incidents/test-drill",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
            json={
                "payment_method": "upi",
                "severity": "high",
                "duration_minutes": 10,
            },
        )

    assert response.status_code == 201
    assert response.json() == {
        "incident_id": str(INCIDENT_ID),
        "label": "TEST MODE INCIDENT DRILL — not provider evidence",
        "severity": "high",
        "payment_method": "upi",
        "expires_at": "2026-08-26T07:10:00Z",
    }
    assert create_drill.await_args.kwargs == {
        "payment_method": "upi",
        "currency": "INR",
        "severity": IncidentSeverity.HIGH,
        "duration_minutes": 10,
    }


@pytest.mark.parametrize(
    ("enabled", "app_env", "headers", "expected_status"),
    [
        (False, "test", {"X-ReclaimRail-Lab-Token": "lab-secret"}, 404),
        (True, "production", {"X-ReclaimRail-Lab-Token": "lab-secret"}, 404),
        (True, "test", {}, 401),
        (True, "test", {"X-ReclaimRail-Lab-Token": "wrong"}, 401),
    ],
)
def test_protects_test_mode_incident_drill(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    app_env: str,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    create_drill = AsyncMock()
    monkeypatch.setattr(
        recovery_incidents,
        "create_test_mode_incident_drill",
        create_drill,
    )
    app.dependency_overrides[get_settings] = lambda: drill_settings(
        enabled=enabled,
        app_env=app_env,
    )

    with TestClient(app) as client:
        response = client.post(
            "/recovery/dashboard/incidents/test-drill",
            headers=headers,
            json={"payment_method": "upi"},
        )

    assert response.status_code == expected_status
    create_drill.assert_not_awaited()
