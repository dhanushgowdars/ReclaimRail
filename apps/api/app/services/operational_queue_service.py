from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.base import Executable

from app.core.config import Settings
from app.db.models.outbox import OutboxMessage, OutboxMessageStatus
from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import RecoveryAction, RecoveryActionStatus, RecoveryCase
from app.db.models.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus
from app.domain.recovery import RecoveryCaseStatus


class OperationalQueueStatus(StrEnum):
    HEALTHY = "healthy"
    ATTENTION_REQUIRED = "attention_required"


@dataclass(frozen=True, slots=True)
class DatabaseQueueMetric:
    name: str
    pending_count: int
    oldest_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class OperationalQueueDiagnostics:
    status: OperationalQueueStatus
    database_queues: tuple[DatabaseQueueMetric, ...]
    webhook_stream_depth: int
    payment_consumer_pending: int
    dead_letter_depth: int
    generated_at: datetime


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Operational diagnostics require a timezone-aware reference time")


def _oldest_age_seconds(
    oldest_at: datetime | None,
    *,
    reference_time: datetime,
) -> float | None:
    if oldest_at is None:
        return None
    return round(max(0.0, (reference_time - oldest_at).total_seconds()), 2)


async def _load_database_metric(
    session: AsyncSession,
    *,
    name: str,
    statement: Executable,
    reference_time: datetime,
) -> DatabaseQueueMetric:
    result = await session.execute(statement)
    pending_count, oldest_at = result.one()
    return DatabaseQueueMetric(
        name=name,
        pending_count=int(pending_count),
        oldest_age_seconds=_oldest_age_seconds(
            oldest_at,
            reference_time=reference_time,
        ),
    )


async def load_database_queue_metrics(
    session: AsyncSession,
    *,
    reference_time: datetime,
) -> tuple[DatabaseQueueMetric, ...]:
    _require_timezone_aware(reference_time)
    specifications = (
        (
            "outbox_dispatch",
            select(func.count(), func.min(OutboxMessage.created_at)).where(
                OutboxMessage.status.in_(
                    (
                        OutboxMessageStatus.PENDING.value,
                        OutboxMessageStatus.PUBLISHING.value,
                    ),
                ),
            ),
        ),
        (
            "outbox_failed",
            select(func.count(), func.min(OutboxMessage.created_at)).where(
                OutboxMessage.status == OutboxMessageStatus.FAILED.value,
            ),
        ),
        (
            "payment_lab_recovery",
            select(func.count(), func.min(PaymentLabRun.updated_at)).where(
                PaymentLabRun.status.in_(
                    (
                        PaymentLabRunStatus.PAYMENT_ATTEMPTED.value,
                        PaymentLabRunStatus.RECOVERY_RUNNING.value,
                    ),
                ),
            ),
        ),
        (
            "recovery_actions",
            select(func.count(), func.min(RecoveryAction.created_at)).where(
                RecoveryAction.status.in_(
                    (
                        RecoveryActionStatus.ALLOWED.value,
                        RecoveryActionStatus.SCHEDULED.value,
                        RecoveryActionStatus.EXECUTING.value,
                    ),
                ),
            ),
        ),
        (
            "recovery_outcomes",
            select(func.count(), func.min(RecoveryOutcome.updated_at)).where(
                RecoveryOutcome.status.in_(
                    (
                        RecoveryOutcomeStatus.PAYMENT_LINK_PENDING.value,
                        RecoveryOutcomeStatus.UNRESOLVED.value,
                    ),
                ),
            ),
        ),
        (
            "late_authorization_compensation",
            select(func.count(), func.min(RecoveryCase.updated_at)).where(
                RecoveryCase.late_authorization_detected_at.is_not(None),
                RecoveryCase.status.in_(
                    (
                        RecoveryCaseStatus.OPEN.value,
                        RecoveryCaseStatus.PLANNING.value,
                        RecoveryCaseStatus.READY.value,
                        RecoveryCaseStatus.EXECUTING.value,
                        RecoveryCaseStatus.WAITING.value,
                    ),
                ),
            ),
        ),
    )
    metrics: list[DatabaseQueueMetric] = []
    for name, statement in specifications:
        metrics.append(
            await _load_database_metric(
                session,
                name=name,
                statement=statement,
                reference_time=reference_time,
            ),
        )
    return tuple(metrics)


def _pending_count(pending_summary: object) -> int:
    if isinstance(pending_summary, dict):
        value = pending_summary.get("pending", 0)
        return int(value) if isinstance(value, int) else 0
    if isinstance(pending_summary, (list, tuple)) and pending_summary:
        value = pending_summary[0]
        return int(value) if isinstance(value, int) else 0
    return 0


async def load_operational_queue_diagnostics(
    session: AsyncSession,
    redis_client: Redis,
    *,
    settings: Settings,
    reference_time: datetime,
) -> OperationalQueueDiagnostics:
    database_queues = await load_database_queue_metrics(
        session,
        reference_time=reference_time,
    )
    webhook_stream_depth = int(await redis_client.xlen(settings.outbox_stream_name))
    dead_letter_depth = int(
        await redis_client.xlen(settings.payment_consumer_dead_letter_stream_name),
    )
    try:
        pending_summary = await redis_client.xpending(
            settings.outbox_stream_name,
            settings.payment_consumer_group_name,
        )
    except ResponseError:
        payment_consumer_pending = 0
    else:
        payment_consumer_pending = _pending_count(pending_summary)

    failed_outbox_count = next(
        metric.pending_count for metric in database_queues if metric.name == "outbox_failed"
    )
    diagnostics_status = (
        OperationalQueueStatus.ATTENTION_REQUIRED
        if failed_outbox_count > 0 or dead_letter_depth > 0
        else OperationalQueueStatus.HEALTHY
    )
    return OperationalQueueDiagnostics(
        status=diagnostics_status,
        database_queues=database_queues,
        webhook_stream_depth=webhook_stream_depth,
        payment_consumer_pending=payment_consumer_pending,
        dead_letter_depth=dead_letter_depth,
        generated_at=reference_time,
    )
