import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import Settings
from app.db.models.outbox import (
    OutboxMessage,
    OutboxMessageStatus,
)

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class OutboxDispatcherConfig:
    stream_name: str
    batch_size: int
    claim_timeout_seconds: int
    max_attempts: int
    retry_base_seconds: float
    retry_max_seconds: float
    stream_max_length: int


@dataclass(frozen=True, slots=True)
class ClaimedOutboxMessage:
    id: UUID
    topic: str
    payload: dict[str, object]
    attempt_count: int


@dataclass(frozen=True, slots=True)
class OutboxDispatchResult:
    claimed: int
    published: int
    retried: int
    failed: int


def create_dispatcher_config(
    settings: Settings,
) -> OutboxDispatcherConfig:
    return OutboxDispatcherConfig(
        stream_name=settings.outbox_stream_name,
        batch_size=settings.outbox_batch_size,
        claim_timeout_seconds=settings.outbox_claim_timeout_seconds,
        max_attempts=settings.outbox_max_attempts,
        retry_base_seconds=settings.outbox_retry_base_seconds,
        retry_max_seconds=settings.outbox_retry_max_seconds,
        stream_max_length=settings.outbox_stream_max_length,
    )


def calculate_retry_delay_seconds(
    attempt_count: int,
    config: OutboxDispatcherConfig,
) -> float:
    exponent = max(attempt_count - 1, 0)
    multiplier = float(2**exponent)
    delay = config.retry_base_seconds * multiplier
    return min(delay, config.retry_max_seconds)


async def claim_outbox_messages(
    session_factory: SessionFactory,
    config: OutboxDispatcherConfig,
) -> list[ClaimedOutboxMessage]:
    now = datetime.now(UTC)
    stale_before = now - timedelta(
        seconds=config.claim_timeout_seconds,
    )

    async with session_factory() as session, session.begin():
        await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxMessageStatus.PUBLISHING.value,
                OutboxMessage.claimed_at.is_not(None),
                OutboxMessage.claimed_at < stale_before,
            )
            .values(
                status=OutboxMessageStatus.PENDING.value,
                claimed_at=None,
                available_at=now,
                last_error=("Dispatcher claim timed out before publication"),
            ),
        )

        result = await session.execute(
            select(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxMessageStatus.PENDING.value,
                OutboxMessage.available_at <= now,
            )
            .order_by(
                OutboxMessage.available_at,
                OutboxMessage.created_at,
            )
            .limit(config.batch_size)
            .with_for_update(skip_locked=True),
        )

        messages = list(result.scalars().all())
        claimed_messages: list[ClaimedOutboxMessage] = []

        for message in messages:
            message.status = OutboxMessageStatus.PUBLISHING.value
            message.claimed_at = now
            message.attempt_count += 1
            message.last_error = None

            claimed_messages.append(
                ClaimedOutboxMessage(
                    id=message.id,
                    topic=message.topic,
                    payload=message.payload,
                    attempt_count=message.attempt_count,
                ),
            )

    return claimed_messages


async def publish_outbox_message(
    redis_client: Redis,
    message: ClaimedOutboxMessage,
    config: OutboxDispatcherConfig,
) -> str:
    payload_json = json.dumps(
        message.payload,
        separators=(",", ":"),
        sort_keys=True,
    )

    broker_message_id = await redis_client.xadd(
        config.stream_name,
        {
            "outbox_message_id": str(message.id),
            "topic": message.topic,
            "payload": payload_json,
        },
        maxlen=config.stream_max_length,
        approximate=True,
    )

    if isinstance(broker_message_id, bytes):
        return broker_message_id.decode("utf-8")

    return str(broker_message_id)


async def mark_outbox_message_published(
    session_factory: SessionFactory,
    message: ClaimedOutboxMessage,
    broker_message_id: str,
) -> None:
    published_at = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message.id,
                OutboxMessage.status == OutboxMessageStatus.PUBLISHING.value,
            )
            .values(
                status=OutboxMessageStatus.PUBLISHED.value,
                broker_message_id=broker_message_id,
                published_at=published_at,
                claimed_at=None,
                last_error=None,
            ),
        )


async def record_outbox_message_failure(
    session_factory: SessionFactory,
    message: ClaimedOutboxMessage,
    error: Exception,
    config: OutboxDispatcherConfig,
) -> bool:
    permanently_failed = message.attempt_count >= config.max_attempts
    now = datetime.now(UTC)

    if permanently_failed:
        status = OutboxMessageStatus.FAILED.value
        available_at = now
    else:
        status = OutboxMessageStatus.PENDING.value
        available_at = now + timedelta(
            seconds=calculate_retry_delay_seconds(
                message.attempt_count,
                config,
            ),
        )

    error_message = (f"{type(error).__name__}: {error}")[:2000]

    async with session_factory() as session, session.begin():
        await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message.id,
                OutboxMessage.status == OutboxMessageStatus.PUBLISHING.value,
            )
            .values(
                status=status,
                available_at=available_at,
                claimed_at=None,
                last_error=error_message,
            ),
        )

    return permanently_failed


async def dispatch_outbox_batch(
    session_factory: SessionFactory,
    redis_client: Redis,
    config: OutboxDispatcherConfig,
) -> OutboxDispatchResult:
    claimed_messages = await claim_outbox_messages(
        session_factory,
        config,
    )

    published = 0
    retried = 0
    failed = 0

    for message in claimed_messages:
        try:
            broker_message_id = await publish_outbox_message(
                redis_client,
                message,
                config,
            )
        except Exception as error:
            permanently_failed = await record_outbox_message_failure(
                session_factory,
                message,
                error,
                config,
            )

            if permanently_failed:
                failed += 1
            else:
                retried += 1
        else:
            await mark_outbox_message_published(
                session_factory,
                message,
                broker_message_id,
            )
            published += 1

    return OutboxDispatchResult(
        claimed=len(claimed_messages),
        published=published,
        retried=retried,
        failed=failed,
    )
