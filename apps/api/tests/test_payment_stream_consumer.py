import json
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from redis.exceptions import ResponseError

from app.services import payment_stream_consumer
from app.services.payment_stream_consumer import (
    PaymentStreamBatchResult,
    PaymentStreamConsumerConfig,
    PaymentStreamDisposition,
    PaymentStreamMessageError,
    PaymentStreamProcessingResult,
    acknowledge_payment_stream_message,
    consume_payment_stream_batch,
    ensure_payment_consumer_group,
    parse_payment_stream_message,
    process_payment_stream_entry,
)
from app.services.payment_webhook_processor import (
    PaymentWebhookDisposition,
    PaymentWebhookEventNotFoundError,
    PaymentWebhookProcessingResult,
)

STREAM_MESSAGE_ID = "1787560160333-0"
OUTBOX_MESSAGE_ID = UUID(
    "10000000-0000-0000-0000-000000000001",
)
WEBHOOK_EVENT_ID = UUID(
    "20000000-0000-0000-0000-000000000001",
)

CONFIG = PaymentStreamConsumerConfig(
    stream_name="reclaimrail:webhook-events:v1",
    group_name="reclaimrail:payment-projectors:v1",
    consumer_name="test-consumer",
    batch_size=25,
    block_milliseconds=1000,
    claim_idle_milliseconds=60_000,
    dead_letter_stream_name=("reclaimrail:payment-events:dead-letter:v1"),
    dead_letter_stream_max_length=10_000,
)


def create_valid_entry() -> tuple[str, dict[str, str]]:
    payload = {
        "schema_version": 1,
        "webhook_event_id": str(WEBHOOK_EVENT_ID),
        "provider": "razorpay",
        "provider_event_id": "evt_payment_failed_001",
        "event_type": "payment.failed",
        "provider_created_at": "2026-08-24T08:00:00+00:00",
    }

    return (
        STREAM_MESSAGE_ID,
        {
            "outbox_message_id": str(OUTBOX_MESSAGE_ID),
            "topic": "webhook.received",
            "payload": json.dumps(payload),
        },
    )


class FakeTransaction:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> None:
        self.events.append("transaction_enter")

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool:
        del exception, traceback

        self.events.append(
            "transaction_rollback" if exception_type is not None else "transaction_commit",
        )
        return False


class FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> "FakeSession":
        self.events.append("session_enter")
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool:
        del exception_type, exception, traceback

        self.events.append("session_exit")
        return False

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self.events)


def test_parses_valid_payment_stream_message() -> None:
    message = parse_payment_stream_message(
        create_valid_entry(),
    )

    assert message.stream_message_id == STREAM_MESSAGE_ID
    assert message.outbox_message_id == OUTBOX_MESSAGE_ID
    assert message.topic == "webhook.received"
    assert message.payload.webhook_event_id == WEBHOOK_EVENT_ID
    assert message.payload.provider == "razorpay"
    assert message.payload.event_type == "payment.failed"


def test_rejects_unsupported_stream_topic() -> None:
    stream_message_id, fields = create_valid_entry()
    invalid_fields = {
        **fields,
        "topic": "unsupported.topic",
    }

    with pytest.raises(
        PaymentStreamMessageError,
        match="Unsupported stream topic",
    ):
        parse_payment_stream_message(
            (stream_message_id, invalid_fields),
        )


@pytest.mark.asyncio
async def test_creates_payment_consumer_group() -> None:
    redis_client = AsyncMock()

    await ensure_payment_consumer_group(
        redis_client,
        CONFIG,
    )

    redis_client.xgroup_create.assert_awaited_once_with(
        CONFIG.stream_name,
        CONFIG.group_name,
        id="0-0",
        mkstream=True,
    )


@pytest.mark.asyncio
async def test_existing_consumer_group_is_idempotent() -> None:
    redis_client = AsyncMock()
    redis_client.xgroup_create.side_effect = ResponseError(
        "BUSYGROUP Consumer Group name already exists",
    )

    await ensure_payment_consumer_group(
        redis_client,
        CONFIG,
    )


@pytest.mark.asyncio
async def test_unexpected_group_creation_error_propagates() -> None:
    redis_client = AsyncMock()
    redis_client.xgroup_create.side_effect = ResponseError(
        "NOAUTH Authentication required",
    )

    with pytest.raises(ResponseError, match="NOAUTH"):
        await ensure_payment_consumer_group(
            redis_client,
            CONFIG,
        )


@pytest.mark.asyncio
async def test_acknowledges_only_after_transaction_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    redis_client = AsyncMock()

    async def fake_processor(
        session: object,
        webhook_event_id: UUID,
        *,
        processed_at: datetime,
    ) -> PaymentWebhookProcessingResult:
        del session

        events.append("process")
        assert webhook_event_id == WEBHOOK_EVENT_ID
        assert processed_at.tzinfo is not None

        return PaymentWebhookProcessingResult(
            webhook_event_id=WEBHOOK_EVENT_ID,
            disposition=PaymentWebhookDisposition.PROJECTED,
            projection=None,
            error=None,
        )

    async def record_ack(
        *arguments: object,
        **keyword_arguments: object,
    ) -> int:
        del arguments, keyword_arguments

        events.append("ack")
        return 1

    monkeypatch.setattr(
        payment_stream_consumer,
        "process_canonical_payment_webhook",
        fake_processor,
    )
    redis_client.xack.side_effect = record_ack

    result = await process_payment_stream_entry(
        lambda: FakeSession(events),  # type: ignore[arg-type]
        redis_client,
        CONFIG,
        create_valid_entry(),
    )

    assert result.disposition is PaymentStreamDisposition.PROJECTED
    assert events == [
        "session_enter",
        "transaction_enter",
        "process",
        "transaction_commit",
        "session_exit",
        "ack",
    ]
    redis_client.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_processing_failure_remains_unacknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    redis_client = AsyncMock()

    async def failing_processor(
        session: object,
        webhook_event_id: UUID,
        *,
        processed_at: datetime,
    ) -> PaymentWebhookProcessingResult:
        del session, webhook_event_id, processed_at

        raise RuntimeError("database temporarily unavailable")

    monkeypatch.setattr(
        payment_stream_consumer,
        "process_canonical_payment_webhook",
        failing_processor,
    )

    result = await process_payment_stream_entry(
        lambda: FakeSession(events),  # type: ignore[arg-type]
        redis_client,
        CONFIG,
        create_valid_entry(),
    )

    assert result.disposition is PaymentStreamDisposition.RETRY
    assert result.error is not None
    assert "database temporarily unavailable" in result.error
    assert "transaction_rollback" in events
    redis_client.xack.assert_not_awaited()
    redis_client.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_message_is_dead_lettered_and_acknowledged() -> None:
    redis_client = AsyncMock()
    session_factory = AsyncMock()

    malformed_entry = (
        STREAM_MESSAGE_ID,
        {
            "outbox_message_id": str(OUTBOX_MESSAGE_ID),
            "topic": "webhook.received",
            "payload": "{invalid-json",
        },
    )

    result = await process_payment_stream_entry(
        session_factory,
        redis_client,
        CONFIG,
        malformed_entry,
    )

    assert result.disposition is (PaymentStreamDisposition.DEAD_LETTERED)
    session_factory.assert_not_called()
    redis_client.xadd.assert_awaited_once()
    redis_client.xack.assert_awaited_once_with(
        CONFIG.stream_name,
        CONFIG.group_name,
        STREAM_MESSAGE_ID,
    )


@pytest.mark.asyncio
async def test_missing_canonical_event_is_dead_lettered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    redis_client = AsyncMock()

    async def missing_event_processor(
        session: object,
        webhook_event_id: UUID,
        *,
        processed_at: datetime,
    ) -> PaymentWebhookProcessingResult:
        del session, processed_at

        raise PaymentWebhookEventNotFoundError(
            f"Missing event: {webhook_event_id}",
        )

    monkeypatch.setattr(
        payment_stream_consumer,
        "process_canonical_payment_webhook",
        missing_event_processor,
    )

    result = await process_payment_stream_entry(
        lambda: FakeSession(events),  # type: ignore[arg-type]
        redis_client,
        CONFIG,
        create_valid_entry(),
    )

    assert result.disposition is (PaymentStreamDisposition.DEAD_LETTERED)
    assert "transaction_rollback" in events
    redis_client.xadd.assert_awaited_once()
    redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_reports_each_processing_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = AsyncMock()
    session_factory = AsyncMock()
    entries = [(f"{index}-0", {}) for index in range(1, 7)]

    dispositions = [
        PaymentStreamDisposition.PROJECTED,
        PaymentStreamDisposition.DUPLICATE,
        PaymentStreamDisposition.SKIPPED,
        PaymentStreamDisposition.FAILED,
        PaymentStreamDisposition.DEAD_LETTERED,
        PaymentStreamDisposition.RETRY,
    ]

    async def fake_fetch(
        redis: object,
        config: PaymentStreamConsumerConfig,
    ) -> list[tuple[str, dict[str, str]]]:
        del redis, config
        return entries

    async def fake_process(
        factory: object,
        redis: object,
        config: PaymentStreamConsumerConfig,
        entry: tuple[str, dict[str, str]],
    ) -> PaymentStreamProcessingResult:
        del factory, redis, config

        index = int(entry[0].split("-", maxsplit=1)[0]) - 1

        return PaymentStreamProcessingResult(
            stream_message_id=entry[0],
            disposition=dispositions[index],
            error=None,
        )

    monkeypatch.setattr(
        payment_stream_consumer,
        "fetch_payment_stream_entries",
        fake_fetch,
    )
    monkeypatch.setattr(
        payment_stream_consumer,
        "process_payment_stream_entry",
        fake_process,
    )

    result = await consume_payment_stream_batch(
        session_factory,
        redis_client,
        CONFIG,
    )

    assert result == PaymentStreamBatchResult(
        received=6,
        projected=1,
        duplicates=1,
        skipped=1,
        failed=1,
        dead_lettered=1,
        retried=1,
    )


@pytest.mark.asyncio
async def test_acknowledgment_uses_configured_stream_and_group() -> None:
    redis_client = AsyncMock()

    await acknowledge_payment_stream_message(
        redis_client,
        CONFIG,
        STREAM_MESSAGE_ID,
    )

    redis_client.xack.assert_awaited_once_with(
        CONFIG.stream_name,
        CONFIG.group_name,
        STREAM_MESSAGE_ID,
    )
