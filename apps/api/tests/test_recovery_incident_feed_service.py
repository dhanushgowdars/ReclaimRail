from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recovery_incident_feed_service import (
    MAX_ACTIVE_INCIDENTS,
    load_active_recovery_incidents,
)

INCIDENT_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 6, 30, tzinfo=UTC)


def build_result(*, incidents: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = incidents
    return result


def build_incident() -> MagicMock:
    incident = MagicMock()
    incident.id = INCIDENT_ID
    incident.status = "open"
    incident.severity = "high"
    incident.scope = "payment_method"
    incident.dimension_value = "upi"
    incident.currency = "INR"
    incident.revenue_at_risk_minor = 725_000
    incident.failure_rate = 0.34
    incident.baseline_failure_rate = 0.03
    incident.absolute_uplift = 0.31
    incident.rate_multiplier = 11.33
    incident.confidence = 0.98
    incident.occurrence_count = 3
    incident.reason_codes = ["failure_rate_spike", "baseline_exceeded"]
    incident.first_detected_at = NOW
    incident.last_detected_at = NOW
    return incident


@pytest.mark.asyncio
async def test_loads_bounded_pii_safe_active_incident_feed() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = build_result(
        incidents=[build_incident()],
    )

    incidents = await load_active_recovery_incidents(
        session,
        currency=" inr ",
        limit=5,
    )

    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.incident_id == INCIDENT_ID
    assert incident.dimension_value == "upi"
    assert incident.revenue_at_risk_minor == 725_000
    assert incident.failure_rate == 0.34
    assert incident.reason_codes == (
        "failure_rate_spike",
        "baseline_exceeded",
    )
    assert session.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit",
    [0, MAX_ACTIVE_INCIDENTS + 1],
)
async def test_rejects_invalid_limit_before_database_access(
    limit: int,
) -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="Active incident limit"):
        await load_active_recovery_incidents(
            session,
            currency="INR",
            limit=limit,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_invalid_currency_before_database_access() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="Dashboard currency"):
        await load_active_recovery_incidents(
            session,
            currency="IN",
        )

    session.execute.assert_not_awaited()
