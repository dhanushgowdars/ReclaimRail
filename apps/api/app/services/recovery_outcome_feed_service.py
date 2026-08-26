from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus
from app.services.recovery_dashboard_service import normalize_dashboard_currency

ALL_RECOVERY_OUTCOME_STATUSES: Final = frozenset(status.value for status in RecoveryOutcomeStatus)
MAX_OUTCOME_FEED_LIMIT: Final = 100
MAX_OUTCOME_FEED_OFFSET: Final = 10_000


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeFeedFilters:
    currency: str
    statuses: tuple[str, ...] = ()
    limit: int = 25
    offset: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "currency",
            normalize_dashboard_currency(self.currency),
        )

        normalized_statuses = tuple(status.strip().lower() for status in self.statuses)
        if any(status not in ALL_RECOVERY_OUTCOME_STATUSES for status in normalized_statuses):
            raise ValueError("Recovery-outcome status filter is invalid")

        object.__setattr__(
            self,
            "statuses",
            tuple(dict.fromkeys(normalized_statuses)),
        )

        if not 1 <= self.limit <= MAX_OUTCOME_FEED_LIMIT:
            raise ValueError(
                f"Recovery outcome limit must be between 1 and {MAX_OUTCOME_FEED_LIMIT}",
            )

        if not 0 <= self.offset <= MAX_OUTCOME_FEED_OFFSET:
            raise ValueError(
                f"Recovery outcome offset must be between 0 and {MAX_OUTCOME_FEED_OFFSET}",
            )


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeFeedItem:
    recovery_outcome_id: UUID
    recovery_case_id: UUID
    recovery_action_id: UUID | None
    status: str
    attribution: str
    original_amount_minor: int
    gross_recovered_minor: int
    reversed_minor: int
    duplicate_collection_prevented_minor: int
    currency: str
    payment_link_id: str | None
    evidence_event_count: int
    occurred_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeFeedPage:
    items: tuple[RecoveryOutcomeFeedItem, ...]
    total_count: int
    limit: int
    offset: int


def build_recovery_outcome_feed_statement(
    filters: RecoveryOutcomeFeedFilters,
) -> Select[tuple[object, ...]]:
    statement = (
        select(
            RecoveryOutcome.id,
            RecoveryOutcome.recovery_case_id,
            RecoveryOutcome.recovery_action_id,
            RecoveryOutcome.status,
            RecoveryOutcome.attribution,
            RecoveryOutcome.original_amount_minor,
            RecoveryOutcome.gross_recovered_minor,
            RecoveryOutcome.reversed_minor,
            RecoveryOutcome.duplicate_collection_prevented_minor,
            RecoveryOutcome.currency,
            RecoveryOutcome.payment_link_id,
            RecoveryOutcome.evidence_event_ids,
            RecoveryOutcome.occurred_at,
            RecoveryOutcome.updated_at,
        )
        .where(
            RecoveryOutcome.currency == filters.currency,
        )
        .order_by(
            RecoveryOutcome.occurred_at.desc(),
            RecoveryOutcome.id.desc(),
        )
        .limit(filters.limit)
        .offset(filters.offset)
    )

    if filters.statuses:
        statement = statement.where(
            RecoveryOutcome.status.in_(filters.statuses),
        )

    return statement


async def load_recovery_outcome_feed(
    session: AsyncSession,
    *,
    filters: RecoveryOutcomeFeedFilters,
) -> RecoveryOutcomeFeedPage:
    count_statement = select(func.count(RecoveryOutcome.id)).where(
        RecoveryOutcome.currency == filters.currency,
    )

    if filters.statuses:
        count_statement = count_statement.where(
            RecoveryOutcome.status.in_(filters.statuses),
        )

    total_count = int(
        (await session.execute(count_statement)).scalar_one(),
    )
    rows = (
        await session.execute(
            build_recovery_outcome_feed_statement(filters),
        )
    ).all()

    items = tuple(
        RecoveryOutcomeFeedItem(
            recovery_outcome_id=row[0],
            recovery_case_id=row[1],
            recovery_action_id=row[2],
            status=row[3],
            attribution=row[4],
            original_amount_minor=row[5],
            gross_recovered_minor=row[6],
            reversed_minor=row[7],
            duplicate_collection_prevented_minor=row[8],
            currency=row[9],
            payment_link_id=row[10],
            evidence_event_count=len(row[11]),
            occurred_at=row[12],
            updated_at=row[13],
        )
        for row in rows
    )

    return RecoveryOutcomeFeedPage(
        items=items,
        total_count=total_count,
        limit=filters.limit,
        offset=filters.offset,
    )
