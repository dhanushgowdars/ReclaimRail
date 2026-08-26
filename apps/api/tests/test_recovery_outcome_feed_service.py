from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recovery_outcome_feed_service import (
    MAX_OUTCOME_FEED_LIMIT,
    MAX_OUTCOME_FEED_OFFSET,
    RecoveryOutcomeFeedFilters,
    load_recovery_outcome_feed,
)

OUTCOME_ID = UUID("10000000-0000-0000-0000-000000000001")
CASE_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 7, 30, tzinfo=UTC)


def build_result(
    *,
    scalar: int | None = None,
    rows: list[object] | None = None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = scalar
    result.all.return_value = rows or []
    return result


def build_row() -> tuple[object, ...]:
    return (
        OUTCOME_ID,
        CASE_ID,
        ACTION_ID,
        "recovered",
        "direct_payment_link",
        349_900,
        349_900,
        0,
        0,
        "INR",
        "plink_demo",
        ["evt_payment_link_paid", "evt_payment_captured"],
        NOW,
        NOW,
    )


def test_normalizes_and_deduplicates_outcome_status_filters() -> None:
    filters = RecoveryOutcomeFeedFilters(
        currency=" inr ",
        statuses=("recovered", " RECOVERED ", "reversed"),
    )

    assert filters.currency == "INR"
    assert filters.statuses == ("recovered", "reversed")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"statuses": ("unknown",)}, "status filter"),
        ({"limit": 0}, "limit"),
        ({"limit": MAX_OUTCOME_FEED_LIMIT + 1}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": MAX_OUTCOME_FEED_OFFSET + 1}, "offset"),
    ],
)
def test_rejects_invalid_outcome_feed_filters(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RecoveryOutcomeFeedFilters(
            currency="INR",
            **changes,
        )


@pytest.mark.asyncio
async def test_loads_pii_safe_paginated_outcome_feed() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        build_result(scalar=1),
        build_result(rows=[build_row()]),
    )
    filters = RecoveryOutcomeFeedFilters(
        currency="INR",
        statuses=("recovered",),
        limit=25,
        offset=0,
    )

    page = await load_recovery_outcome_feed(
        session,
        filters=filters,
    )

    assert page.total_count == 1
    assert page.limit == 25
    assert page.offset == 0
    assert len(page.items) == 1

    item = page.items[0]
    assert item.recovery_outcome_id == OUTCOME_ID
    assert item.recovery_case_id == CASE_ID
    assert item.gross_recovered_minor == 349_900
    assert item.evidence_event_count == 2
    assert session.execute.await_count == 2
