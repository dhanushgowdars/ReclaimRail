from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_dashboard
from app.core.database import get_database_session
from app.main import app
from app.services.recovery_dashboard_service import RecoveryDashboardSummary


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def database_session_override() -> AsyncIterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session

    yield

    app.dependency_overrides.clear()


def build_summary(*, currency: str = "INR") -> RecoveryDashboardSummary:
    return RecoveryDashboardSummary(
        currency=currency,
        revenue_at_risk_minor=725_000,
        verified_recovered_minor=349_900,
        duplicate_collection_prevented_minor=100,
        active_incident_revenue_at_risk_minor=500_000,
        active_case_count=4,
        recovered_case_count=2,
        pending_outcome_count=1,
        open_incident_count=2,
    )


def test_dashboard_summary_returns_verified_business_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_summary = AsyncMock(
        return_value=build_summary(),
    )
    monkeypatch.setattr(
        recovery_dashboard,
        "load_recovery_dashboard_summary",
        load_summary,
    )

    with TestClient(app) as client:
        response = client.get("/recovery/dashboard/summary")

    assert response.status_code == 200

    body = response.json()

    assert body["currency"] == "INR"
    assert body["revenue_at_risk_minor"] == 725_000
    assert body["verified_recovered_minor"] == 349_900
    assert body["duplicate_collection_prevented_minor"] == 100
    assert body["active_incident_revenue_at_risk_minor"] == 500_000
    assert body["active_case_count"] == 4
    assert body["recovered_case_count"] == 2
    assert body["pending_outcome_count"] == 1
    assert body["open_incident_count"] == 2
    assert body["generated_at"].endswith("Z")

    assert load_summary.await_count == 1
    assert load_summary.await_args.kwargs["currency"] == "INR"


def test_dashboard_summary_accepts_explicit_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_summary = AsyncMock(
        return_value=build_summary(currency="USD"),
    )
    monkeypatch.setattr(
        recovery_dashboard,
        "load_recovery_dashboard_summary",
        load_summary,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/summary",
            params={"currency": "usd"},
        )

    assert response.status_code == 200
    assert response.json()["currency"] == "USD"
    assert load_summary.await_args.kwargs["currency"] == "usd"


@pytest.mark.parametrize(
    "currency",
    ["IN", "INR1", "12A"],
)
def test_dashboard_summary_rejects_invalid_currency(currency: str) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/summary",
            params={"currency": currency},
        )

    assert response.status_code == 422
