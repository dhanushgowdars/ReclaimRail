from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_incidents
from app.core.database import get_database_session
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
