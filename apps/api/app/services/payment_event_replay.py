import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.event_replay import PaymentEventReplayAudit


class PaymentEventReplayError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PaymentEventReplayResult:
    audit_id: str
    target_message_id: str


async def replay_dead_letter_event(
    session: AsyncSession,
    redis_client: Redis,
    *,
    dead_letter_stream: str,
    source_message_id: str,
    target_stream: str,
    requested_by: str,
    reason: str,
) -> PaymentEventReplayResult:
    """Replay exactly one DLQ entry with explicit operator intent and audit."""
    for name, value in (
        ("dead_letter_stream", dead_letter_stream),
        ("source_message_id", source_message_id),
        ("target_stream", target_stream),
        ("requested_by", requested_by),
        ("reason", reason),
    ):
        if not value.strip():
            raise PaymentEventReplayError(f"{name} cannot be empty")

    existing = await session.scalar(
        select(PaymentEventReplayAudit).where(
            PaymentEventReplayAudit.source_stream == dead_letter_stream,
            PaymentEventReplayAudit.source_message_id == source_message_id,
        ),
    )
    if existing is not None:
        raise PaymentEventReplayError("This dead-letter entry has already been replayed")

    entries = await redis_client.xrange(
        dead_letter_stream,
        min=source_message_id,
        max=source_message_id,
        count=1,
    )
    if not entries:
        raise PaymentEventReplayError("Dead-letter entry was not found")
    _, raw_dlq_fields = entries[0]
    if raw_dlq_fields is None:
        raise PaymentEventReplayError("Dead-letter entry has no fields")
    dlq_fields = cast(dict[str, str], raw_dlq_fields)
    try:
        original_fields = json.loads(dlq_fields["fields"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise PaymentEventReplayError(
            "Dead-letter entry does not contain replayable fields"
        ) from error
    if not isinstance(original_fields, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in original_fields.items()
    ):
        raise PaymentEventReplayError("Dead-letter source fields are invalid")

    audit = PaymentEventReplayAudit(
        id=uuid4(),
        source_stream=dead_letter_stream,
        source_message_id=source_message_id,
        target_stream=target_stream,
        requested_by=requested_by.strip(),
        reason=reason.strip(),
        status="authorized",
        source_fields=original_fields,
    )
    session.add(audit)
    try:
        await session.flush()
    except IntegrityError as error:
        raise PaymentEventReplayError("This dead-letter entry has already been replayed") from error

    target_message_id = await redis_client.xadd(target_stream, original_fields)
    audit.target_message_id = str(target_message_id)
    audit.status = "published"
    audit.completed_at = datetime.now(UTC)
    await session.flush()
    return PaymentEventReplayResult(
        audit_id=str(audit.id),
        target_message_id=str(target_message_id),
    )
