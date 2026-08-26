from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recovery_dashboard_service import (
    load_recovery_dashboard_summary,
    normalize_dashboard_currency,
)


def build_query_result(*values: int) -> MagicMock:
    result = MagicMock()
    result.one.return_value = values
    return result


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("inr", "INR"),
        (" INR ", "INR"),
        ("usd", "USD"),
    ],
)
def test_normalizes_dashboard_currency(
    value: str,
    expected: str,
) -> None:
    assert normalize_dashboard_currency(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "IN", "INR1", "12A", "₹₹₹"],
)
def test_rejects_invalid_dashboard_currency(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="three-letter alphabetic code",
    ):
        normalize_dashboard_currency(value)


@pytest.mark.asyncio
async def test_loads_currency_scoped_verified_dashboard_summary() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        build_query_result(725_000, 4, 2),
        build_query_result(349_900, 100, 1),
        build_query_result(500_000, 2),
    )

    summary = await load_recovery_dashboard_summary(
        session,
        currency=" inr ",
    )

    assert summary.currency == "INR"
    assert summary.revenue_at_risk_minor == 725_000
    assert summary.verified_recovered_minor == 349_900
    assert summary.duplicate_collection_prevented_minor == 100
    assert summary.active_incident_revenue_at_risk_minor == 500_000
    assert summary.active_case_count == 4
    assert summary.recovered_case_count == 2
    assert summary.pending_outcome_count == 1
    assert summary.open_incident_count == 2
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_rejects_invalid_currency_before_database_access() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError):
        await load_recovery_dashboard_summary(
            session,
            currency="INR1",
        )

    session.execute.assert_not_awaited()
