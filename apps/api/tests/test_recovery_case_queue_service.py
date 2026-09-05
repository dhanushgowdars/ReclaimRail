from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recovery_case_queue_service import (
    DEFAULT_QUEUE_STATUSES,
    MAX_QUEUE_LIMIT,
    MAX_QUEUE_OFFSET,
    RecoveryCaseQueueFilters,
    load_recovery_case_queue,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
INCIDENT_ID = UUID("20000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 4, 30, tzinfo=UTC)


def build_query_result(
    *,
    scalar: int | None = None,
    rows: list[tuple[object, ...]] | None = None,
) -> MagicMock:
    result = MagicMock()

    if scalar is not None:
        result.scalar_one.return_value = scalar

    if rows is not None:
        result.all.return_value = rows

    return result


def build_row() -> tuple[object, ...]:
    return (
        CASE_ID,
        "ready",
        349_900,
        "INR",
        "upi",
        INCIDENT_ID,
        1,
        NOW,
        None,
        NOW,
        None,
        NOW,
        "create_payment_link",
        "succeeded",
        "allow",
        None,
        None,
        None,
        None,
        None,
        "payment_link_pending",
    )


def test_default_filters_include_complete_persisted_case_history() -> None:
    filters = RecoveryCaseQueueFilters(currency=" inr ")

    assert filters.currency == "INR"
    assert filters.statuses == DEFAULT_QUEUE_STATUSES
    assert filters.limit == 25
    assert filters.offset == 0


def test_filters_normalize_and_deduplicate_requested_statuses() -> None:
    filters = RecoveryCaseQueueFilters(
        currency="inr",
        statuses=("READY", "waiting", "ready"),
        source_incident_id=INCIDENT_ID,
        limit=50,
        offset=25,
    )

    assert filters.statuses == ("ready", "waiting")
    assert filters.source_incident_id == INCIDENT_ID
    assert filters.limit == 50
    assert filters.offset == 25


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"statuses": ()}, "At least one"),
        ({"statuses": ("unknown",)}, "status filter"),
        ({"limit": 0}, "limit"),
        ({"limit": MAX_QUEUE_LIMIT + 1}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": MAX_QUEUE_OFFSET + 1}, "offset"),
    ],
)
def test_filters_reject_invalid_bounds_or_statuses(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RecoveryCaseQueueFilters(
            currency="INR",
            **changes,
        )


@pytest.mark.asyncio
async def test_loads_bounded_pii_safe_recovery_case_queue() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        build_query_result(scalar=1),
        build_query_result(rows=[build_row()]),
    )

    page = await load_recovery_case_queue(
        session,
        filters=RecoveryCaseQueueFilters(
            currency="INR",
            source_incident_id=INCIDENT_ID,
        ),
    )

    assert page.total_count == 1
    assert page.limit == 25
    assert page.offset == 0
    assert len(page.items) == 1

    item = page.items[0]
    assert item.recovery_case_id == CASE_ID
    assert item.status == "ready"
    assert item.amount_minor == 349_900
    assert item.currency == "INR"
    assert item.payment_method == "upi"
    assert item.source_incident_id == INCIDENT_ID
    assert item.closed_at is None
    assert item.latest_action_type == "create_payment_link"
    assert item.latest_action_status == "succeeded"
    assert item.latest_action_policy_outcome == "allow"
    assert item.latest_approval_status is None
    assert item.latest_approval_reason is None
    assert item.latest_approval_decision_reason is None
    assert item.latest_approval_decided_at is None
    assert item.latest_approval_decided_by is None
    assert item.outcome_status == "payment_link_pending"
    assert session.execute.await_count == 2
