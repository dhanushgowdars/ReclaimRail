from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services import outbox_dispatcher
from app.services.outbox_dispatcher import (
    ClaimedOutboxMessage,
    OutboxDispatcherConfig,
    calculate_retry_delay_seconds,
    dispatch_outbox_batch,
    publish_outbox_message,
)

MESSAGE_ID_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MESSAGE_ID_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def make_config() -> OutboxDispatcherConfig:
    return OutboxDispatcherConfig(
        stream_name="reclaimrail:webhook-events:v1",
        batch_size=25,
        claim_timeout_seconds=60,
        max_attempts=5,
        retry_base_seconds=2.0,
        retry_max_seconds=300.0,
        stream_max_length=10_000,
    )


def make_message(
    message_id: UUID,
    *,
    attempt_count: int = 1,
) -> ClaimedOutboxMessage:
    return ClaimedOutboxMessage(
        id=message_id,
        topic="webhook.received",
        payload={
            "schema_version": 1,
            "event_type": "payment.failed",
        },
        attempt_count=attempt_count,
    )


def test_calculates_bounded_exponential_retry_delay() -> None:
    config = make_config()

    assert calculate_retry_delay_seconds(1, config) == 2.0
    assert calculate_retry_delay_seconds(2, config) == 4.0
    assert calculate_retry_delay_seconds(3, config) == 8.0
    assert calculate_retry_delay_seconds(20, config) == 300.0


@pytest.mark.asyncio
async def test_publishes_message_to_redis_stream() -> None:
    config = make_config()
    message = make_message(MESSAGE_ID_A)
    redis_client = AsyncMock()
    redis_client.xadd.return_value = b"1787550000000-0"

    broker_message_id = await publish_outbox_message(
        redis_client,
        message,
        config,
    )

    assert broker_message_id == "1787550000000-0"

    redis_client.xadd.assert_awaited_once_with(
        "reclaimrail:webhook-events:v1",
        {
            "outbox_message_id": str(MESSAGE_ID_A),
            "topic": "webhook.received",
            "payload": ('{"event_type":"payment.failed","schema_version":1}'),
        },
        maxlen=10_000,
        approximate=True,
    )


@pytest.mark.asyncio
async def test_dispatches_success_and_schedules_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config()
    published_message = make_message(MESSAGE_ID_A)
    retry_message = make_message(MESSAGE_ID_B)

    claim_mock = AsyncMock(
        return_value=[
            published_message,
            retry_message,
        ],
    )
    publish_mock = AsyncMock(
        side_effect=[
            "1787550000000-0",
            ConnectionError("Redis unavailable"),
        ],
    )
    mark_published_mock = AsyncMock()
    record_failure_mock = AsyncMock(return_value=False)

    monkeypatch.setattr(
        outbox_dispatcher,
        "claim_outbox_messages",
        claim_mock,
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "publish_outbox_message",
        publish_mock,
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "mark_outbox_message_published",
        mark_published_mock,
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "record_outbox_message_failure",
        record_failure_mock,
    )

    session_factory = MagicMock()
    redis_client = AsyncMock()

    result = await dispatch_outbox_batch(
        session_factory,
        redis_client,
        config,
    )

    assert result.claimed == 2
    assert result.published == 1
    assert result.retried == 1
    assert result.failed == 0

    mark_published_mock.assert_awaited_once_with(
        session_factory,
        published_message,
        "1787550000000-0",
    )

    assert record_failure_mock.await_count == 1
    failure_arguments = record_failure_mock.await_args.args
    assert failure_arguments[0] is session_factory
    assert failure_arguments[1] == retry_message
    assert isinstance(failure_arguments[2], ConnectionError)
    assert failure_arguments[3] == config


@pytest.mark.asyncio
async def test_marks_message_failed_after_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config()
    message = make_message(
        MESSAGE_ID_A,
        attempt_count=config.max_attempts,
    )

    monkeypatch.setattr(
        outbox_dispatcher,
        "claim_outbox_messages",
        AsyncMock(return_value=[message]),
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "publish_outbox_message",
        AsyncMock(
            side_effect=ConnectionError("Redis unavailable"),
        ),
    )
    mark_published_mock = AsyncMock()
    monkeypatch.setattr(
        outbox_dispatcher,
        "mark_outbox_message_published",
        mark_published_mock,
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "record_outbox_message_failure",
        AsyncMock(return_value=True),
    )

    result = await dispatch_outbox_batch(
        MagicMock(),
        AsyncMock(),
        config,
    )

    assert result.claimed == 1
    assert result.published == 0
    assert result.retried == 0
    assert result.failed == 1
    mark_published_mock.assert_not_awaited()
