from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services.operational_queue_service import (
    OperationalQueueStatus,
    load_database_queue_metrics,
    load_operational_queue_diagnostics,
)

NOW = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)


def query_result(count: int, oldest_at: datetime | None) -> MagicMock:
    result = MagicMock()
    result.one.return_value = (count, oldest_at)
    return result


@pytest.mark.asyncio
async def test_database_queue_metrics_include_all_operational_queues() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(2, NOW - timedelta(seconds=10)),
        query_result(1, NOW - timedelta(seconds=20)),
        query_result(3, NOW - timedelta(seconds=30)),
        query_result(4, NOW - timedelta(seconds=40)),
        query_result(5, NOW - timedelta(seconds=50)),
        query_result(6, NOW - timedelta(seconds=60)),
        query_result(7, NOW - timedelta(seconds=70)),
    ]

    metrics = await load_database_queue_metrics(session, reference_time=NOW)

    assert [metric.name for metric in metrics] == [
        "outbox_dispatch",
        "outbox_failed",
        "payment_lab_recovery",
        "recovery_approvals",
        "recovery_actions",
        "recovery_outcomes",
        "late_authorization_compensation",
    ]
    assert [metric.pending_count for metric in metrics] == [2, 1, 3, 4, 5, 6, 7]
    assert metrics[-1].oldest_age_seconds == 70
    assert session.execute.await_count == 7


@pytest.mark.asyncio
async def test_dead_letters_or_failed_outbox_require_attention() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(0, None),
        query_result(0, None),
        query_result(1, NOW),
        query_result(0, None),
        query_result(0, None),
        query_result(0, None),
        query_result(0, None),
    ]
    redis_client = AsyncMock()
    redis_client.xlen.side_effect = (7, 2)
    redis_client.xpending.return_value = {"pending": 3}
    settings = Settings(
        outbox_stream_name="events",
        payment_consumer_group_name="projectors",
        payment_consumer_dead_letter_stream_name="dead-letters",
    )

    diagnostics = await load_operational_queue_diagnostics(
        session,
        redis_client,
        settings=settings,
        reference_time=NOW,
    )

    assert diagnostics.status is OperationalQueueStatus.ATTENTION_REQUIRED
    assert diagnostics.webhook_stream_depth == 7
    assert diagnostics.payment_consumer_pending == 3
    assert diagnostics.dead_letter_depth == 2
    assert redis_client.xpending.await_args.args == ("events", "projectors")


@pytest.mark.asyncio
async def test_missing_consumer_group_reports_zero_pending() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [query_result(0, None) for _ in range(7)]
    redis_client = AsyncMock()
    redis_client.xlen.side_effect = (0, 0)
    redis_client.xpending.side_effect = ResponseError("NOGROUP")

    diagnostics = await load_operational_queue_diagnostics(
        session,
        redis_client,
        settings=Settings(),
        reference_time=NOW,
    )

    assert diagnostics.status is OperationalQueueStatus.HEALTHY
    assert diagnostics.payment_consumer_pending == 0


@pytest.mark.asyncio
async def test_reference_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await load_database_queue_metrics(
            AsyncMock(spec=AsyncSession),
            reference_time=datetime(2026, 8, 28, 6, 0),
        )
