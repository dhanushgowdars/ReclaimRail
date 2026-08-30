from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery import RecoveryAction, RecoveryCase
from app.db.models.recovery_outcome import RecoveryOutcome
from app.domain.recovery import RecoveryCaseStatus
from app.services.recovery_dashboard_service import normalize_dashboard_currency

DEFAULT_QUEUE_STATUSES: Final = (
    RecoveryCaseStatus.OPEN.value,
    RecoveryCaseStatus.PLANNING.value,
    RecoveryCaseStatus.READY.value,
    RecoveryCaseStatus.EXECUTING.value,
    RecoveryCaseStatus.WAITING.value,
    RecoveryCaseStatus.ESCALATED.value,
)
ALL_RECOVERY_CASE_STATUSES: Final = frozenset(status.value for status in RecoveryCaseStatus)
MAX_QUEUE_LIMIT: Final = 100
MAX_QUEUE_OFFSET: Final = 10_000


@dataclass(frozen=True, slots=True)
class RecoveryCaseQueueFilters:
    currency: str
    statuses: tuple[str, ...] = DEFAULT_QUEUE_STATUSES
    source_incident_id: UUID | None = None
    limit: int = 25
    offset: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "currency",
            normalize_dashboard_currency(self.currency),
        )

        if not self.statuses:
            raise ValueError("At least one recovery-case status is required")

        normalized_statuses = tuple(status.strip().lower() for status in self.statuses)

        if any(status not in ALL_RECOVERY_CASE_STATUSES for status in normalized_statuses):
            raise ValueError("Recovery-case status filter is invalid")

        object.__setattr__(
            self,
            "statuses",
            tuple(dict.fromkeys(normalized_statuses)),
        )

        if not 1 <= self.limit <= MAX_QUEUE_LIMIT:
            raise ValueError(
                f"Recovery queue limit must be between 1 and {MAX_QUEUE_LIMIT}",
            )

        if not 0 <= self.offset <= MAX_QUEUE_OFFSET:
            raise ValueError(
                f"Recovery queue offset must be between 0 and {MAX_QUEUE_OFFSET}",
            )


@dataclass(frozen=True, slots=True)
class RecoveryCaseQueueItem:
    recovery_case_id: UUID
    status: str
    amount_minor: int
    currency: str
    payment_method: str | None
    source_incident_id: UUID | None
    recovery_attempt_count: int
    next_action_at: datetime | None
    late_authorization_detected_at: datetime | None
    opened_at: datetime
    updated_at: datetime
    latest_action_type: str | None
    latest_action_status: str | None
    latest_action_policy_outcome: str | None
    outcome_status: str | None


@dataclass(frozen=True, slots=True)
class RecoveryCaseQueuePage:
    items: tuple[RecoveryCaseQueueItem, ...]
    total_count: int
    limit: int
    offset: int


def build_recovery_case_queue_statement(
    filters: RecoveryCaseQueueFilters,
) -> Select[tuple[object, ...]]:
    latest_action_id = (
        select(RecoveryAction.id)
        .where(RecoveryAction.recovery_case_id == RecoveryCase.id)
        .order_by(
            RecoveryAction.sequence_number.desc(),
            RecoveryAction.id.desc(),
        )
        .limit(1)
        .correlate(RecoveryCase)
        .scalar_subquery()
    )

    statement = (
        select(
            RecoveryCase.id,
            RecoveryCase.status,
            RecoveryCase.amount_minor,
            RecoveryCase.currency,
            RecoveryCase.payment_method,
            RecoveryCase.source_incident_id,
            RecoveryCase.recovery_attempt_count,
            RecoveryCase.next_action_at,
            RecoveryCase.late_authorization_detected_at,
            RecoveryCase.opened_at,
            RecoveryCase.updated_at,
            RecoveryAction.action_type,
            RecoveryAction.status,
            RecoveryAction.policy_outcome,
            RecoveryOutcome.status,
        )
        .outerjoin(
            RecoveryOutcome,
            RecoveryOutcome.recovery_case_id == RecoveryCase.id,
        )
        .outerjoin(
            RecoveryAction,
            RecoveryAction.id == latest_action_id,
        )
        .where(
            RecoveryCase.currency == filters.currency,
            RecoveryCase.status.in_(filters.statuses),
        )
        .order_by(
            RecoveryCase.next_action_at.asc().nulls_last(),
            RecoveryCase.updated_at.desc(),
            RecoveryCase.id.desc(),
        )
        .limit(filters.limit)
        .offset(filters.offset)
    )

    if filters.source_incident_id is not None:
        statement = statement.where(
            RecoveryCase.source_incident_id == filters.source_incident_id,
        )

    return statement


async def load_recovery_case_queue(
    session: AsyncSession,
    *,
    filters: RecoveryCaseQueueFilters,
) -> RecoveryCaseQueuePage:
    count_statement = select(func.count(RecoveryCase.id)).where(
        RecoveryCase.currency == filters.currency,
        RecoveryCase.status.in_(filters.statuses),
    )

    if filters.source_incident_id is not None:
        count_statement = count_statement.where(
            RecoveryCase.source_incident_id == filters.source_incident_id,
        )

    total_count = int(
        (await session.execute(count_statement)).scalar_one(),
    )
    rows = (
        await session.execute(
            build_recovery_case_queue_statement(filters),
        )
    ).all()

    items = tuple(
        RecoveryCaseQueueItem(
            recovery_case_id=row[0],
            status=row[1],
            amount_minor=row[2],
            currency=row[3],
            payment_method=row[4],
            source_incident_id=row[5],
            recovery_attempt_count=row[6],
            next_action_at=row[7],
            late_authorization_detected_at=row[8],
            opened_at=row[9],
            updated_at=row[10],
            latest_action_type=row[11],
            latest_action_status=row[12],
            latest_action_policy_outcome=row[13],
            outcome_status=row[14],
        )
        for row in rows
    )

    return RecoveryCaseQueuePage(
        items=items,
        total_count=total_count,
        limit=filters.limit,
        offset=filters.offset,
    )
