import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services.payment_webhook_processor import (
    PaymentWebhookDisposition,
    PaymentWebhookEventNotFoundError,
    process_canonical_payment_webhook,
)

SessionFactory = async_sessionmaker[AsyncSession]
RedisStreamEntry = tuple[str, dict[str, str]]


@dataclass(frozen=True, slots=True)
class PaymentStreamConsumerConfig:
    stream_name: str
    group_name: str
    consumer_name: str
    batch_size: int
    block_milliseconds: int
    claim_idle_milliseconds: int
    dead_letter_stream_name: str
    dead_letter_stream_max_length: int


class WebhookReceivedPayload(BaseModel):
    schema_version: Literal[1]
    webhook_event_id: UUID
    provider: Literal["razorpay"]
    provider_event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    provider_created_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class PaymentStreamMessage:
    stream_message_id: str
    outbox_message_id: UUID
    topic: str
    payload: WebhookReceivedPayload
    raw_fields: dict[str, str]


class PaymentStreamMessageError(ValueError):
    pass


class PaymentStreamDisposition(StrEnum):
    PROJECTED = "projected"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class PaymentStreamProcessingResult:
    stream_message_id: str
    disposition: PaymentStreamDisposition
    error: str | None


@dataclass(frozen=True, slots=True)
class PaymentStreamBatchResult:
    received: int
    projected: int
    duplicates: int
    skipped: int
    failed: int
    dead_lettered: int
    retried: int


def create_payment_consumer_config(
    settings: Settings,
    *,
    consumer_name: str,
) -> PaymentStreamConsumerConfig:
    return PaymentStreamConsumerConfig(
        stream_name=settings.outbox_stream_name,
        group_name=settings.payment_consumer_group_name,
        consumer_name=consumer_name,
        batch_size=settings.payment_consumer_batch_size,
        block_milliseconds=(settings.payment_consumer_block_milliseconds),
        claim_idle_milliseconds=(settings.payment_consumer_claim_idle_milliseconds),
        dead_letter_stream_name=(settings.payment_consumer_dead_letter_stream_name),
        dead_letter_stream_max_length=(settings.payment_consumer_dead_letter_stream_max_length),
    )


async def ensure_payment_consumer_group(
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
) -> None:
    try:
        await redis_client.xgroup_create(
            config.stream_name,
            config.group_name,
            id="0-0",
            mkstream=True,
        )
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


def decode_xreadgroup_response(
    response: object,
) -> list[RedisStreamEntry]:
    streams = cast(
        list[tuple[str, list[RedisStreamEntry]]],
        response,
    )

    entries: list[RedisStreamEntry] = []

    for _, stream_entries in streams:
        entries.extend(stream_entries)

    return entries


def decode_xautoclaim_response(
    response: object,
) -> list[RedisStreamEntry]:
    values = cast(list[object], response)

    if len(values) < 2:
        raise RuntimeError(
            "Redis XAUTOCLAIM returned an invalid response",
        )

    return cast(list[RedisStreamEntry], values[1])


async def claim_stale_payment_stream_entries(
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
) -> list[RedisStreamEntry]:
    response: object = await redis_client.xautoclaim(
        config.stream_name,
        config.group_name,
        config.consumer_name,
        config.claim_idle_milliseconds,
        start_id="0-0",
        count=config.batch_size,
    )

    return decode_xautoclaim_response(response)


async def read_new_payment_stream_entries(
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
) -> list[RedisStreamEntry]:
    response: object = await redis_client.xreadgroup(
        config.group_name,
        config.consumer_name,
        streams={config.stream_name: ">"},
        count=config.batch_size,
        block=config.block_milliseconds,
    )

    return decode_xreadgroup_response(response)


async def fetch_payment_stream_entries(
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
) -> list[RedisStreamEntry]:
    reclaimed_entries = await claim_stale_payment_stream_entries(
        redis_client,
        config,
    )

    if reclaimed_entries:
        return reclaimed_entries

    return await read_new_payment_stream_entries(
        redis_client,
        config,
    )


def parse_payment_stream_message(
    entry: RedisStreamEntry,
) -> PaymentStreamMessage:
    stream_message_id, fields = entry

    try:
        outbox_message_id = UUID(fields["outbox_message_id"])
        topic = fields["topic"]
        raw_payload = fields["payload"]

        if topic != "webhook.received":
            raise ValueError(
                f"Unsupported stream topic: {topic}",
            )

        decoded_payload: object = json.loads(raw_payload)
        payload = WebhookReceivedPayload.model_validate(
            decoded_payload,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PaymentStreamMessageError(
            f"Invalid payment stream message: {error}",
        ) from error

    return PaymentStreamMessage(
        stream_message_id=stream_message_id,
        outbox_message_id=outbox_message_id,
        topic=topic,
        payload=payload,
        raw_fields=fields,
    )


async def acknowledge_payment_stream_message(
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
    stream_message_id: str,
) -> None:
    await redis_client.xack(
        config.stream_name,
        config.group_name,
        stream_message_id,
    )


async def dead_letter_payment_stream_message(
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
    *,
    stream_message_id: str,
    fields: dict[str, str],
    error: Exception,
) -> None:
    error_message = f"{type(error).__name__}: {error}"[:2000]

    await redis_client.xadd(
        config.dead_letter_stream_name,
        {
            "source_stream": config.stream_name,
            "source_message_id": stream_message_id,
            "error": error_message,
            "failed_at": datetime.now(UTC).isoformat(),
            "fields": json.dumps(
                fields,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
        maxlen=config.dead_letter_stream_max_length,
        approximate=True,
    )


def map_webhook_disposition(
    disposition: PaymentWebhookDisposition,
) -> PaymentStreamDisposition:
    mapping = {
        PaymentWebhookDisposition.PROJECTED: (PaymentStreamDisposition.PROJECTED),
        PaymentWebhookDisposition.DUPLICATE: (PaymentStreamDisposition.DUPLICATE),
        PaymentWebhookDisposition.SKIPPED: (PaymentStreamDisposition.SKIPPED),
        PaymentWebhookDisposition.FAILED: (PaymentStreamDisposition.FAILED),
    }

    return mapping[disposition]


async def process_payment_stream_entry(
    session_factory: SessionFactory,
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
    entry: RedisStreamEntry,
) -> PaymentStreamProcessingResult:
    stream_message_id, fields = entry

    try:
        message = parse_payment_stream_message(entry)
    except PaymentStreamMessageError as error:
        await dead_letter_payment_stream_message(
            redis_client,
            config,
            stream_message_id=stream_message_id,
            fields=fields,
            error=error,
        )
        await acknowledge_payment_stream_message(
            redis_client,
            config,
            stream_message_id,
        )

        return PaymentStreamProcessingResult(
            stream_message_id=stream_message_id,
            disposition=PaymentStreamDisposition.DEAD_LETTERED,
            error=str(error),
        )

    try:
        async with session_factory() as session, session.begin():
            processing_result = await process_canonical_payment_webhook(
                session,
                message.payload.webhook_event_id,
                processed_at=datetime.now(UTC),
            )
    except asyncio.CancelledError:
        raise
    except PaymentWebhookEventNotFoundError as error:
        await dead_letter_payment_stream_message(
            redis_client,
            config,
            stream_message_id=stream_message_id,
            fields=fields,
            error=error,
        )
        await acknowledge_payment_stream_message(
            redis_client,
            config,
            stream_message_id,
        )

        return PaymentStreamProcessingResult(
            stream_message_id=stream_message_id,
            disposition=PaymentStreamDisposition.DEAD_LETTERED,
            error=str(error),
        )
    except Exception as error:
        return PaymentStreamProcessingResult(
            stream_message_id=stream_message_id,
            disposition=PaymentStreamDisposition.RETRY,
            error=f"{type(error).__name__}: {error}"[:2000],
        )

    await acknowledge_payment_stream_message(
        redis_client,
        config,
        stream_message_id,
    )

    return PaymentStreamProcessingResult(
        stream_message_id=stream_message_id,
        disposition=map_webhook_disposition(
            processing_result.disposition,
        ),
        error=processing_result.error,
    )


async def consume_payment_stream_batch(
    session_factory: SessionFactory,
    redis_client: Redis,
    config: PaymentStreamConsumerConfig,
) -> PaymentStreamBatchResult:
    entries = await fetch_payment_stream_entries(
        redis_client,
        config,
    )

    projected = 0
    duplicates = 0
    skipped = 0
    failed = 0
    dead_lettered = 0
    retried = 0

    for entry in entries:
        result = await process_payment_stream_entry(
            session_factory,
            redis_client,
            config,
            entry,
        )

        if result.disposition is PaymentStreamDisposition.PROJECTED:
            projected += 1
        elif result.disposition is PaymentStreamDisposition.DUPLICATE:
            duplicates += 1
        elif result.disposition is PaymentStreamDisposition.SKIPPED:
            skipped += 1
        elif result.disposition is PaymentStreamDisposition.FAILED:
            failed += 1
        elif result.disposition is (PaymentStreamDisposition.DEAD_LETTERED):
            dead_lettered += 1
        elif result.disposition is PaymentStreamDisposition.RETRY:
            retried += 1

    return PaymentStreamBatchResult(
        received=len(entries),
        projected=projected,
        duplicates=duplicates,
        skipped=skipped,
        failed=failed,
        dead_lettered=dead_lettered,
        retried=retried,
    )
