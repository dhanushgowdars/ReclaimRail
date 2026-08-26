from dataclasses import dataclass
from typing import Final

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import RevenueIncident, RevenueIncidentStatus
from app.db.models.recovery import RecoveryCase
from app.db.models.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus
from app.domain.recovery import RecoveryCaseStatus

ACTIVE_CASE_STATUSES: Final = (
    RecoveryCaseStatus.OPEN.value,
    RecoveryCaseStatus.PLANNING.value,
    RecoveryCaseStatus.READY.value,
    RecoveryCaseStatus.EXECUTING.value,
    RecoveryCaseStatus.WAITING.value,
    RecoveryCaseStatus.ESCALATED.value,
)
ACTIVE_INCIDENT_STATUSES: Final = (
    RevenueIncidentStatus.OPEN.value,
    RevenueIncidentStatus.INVESTIGATING.value,
    RevenueIncidentStatus.MITIGATING.value,
)
PENDING_OUTCOME_STATUSES: Final = (
    RecoveryOutcomeStatus.PAYMENT_LINK_PENDING.value,
    RecoveryOutcomeStatus.UNRESOLVED.value,
)


@dataclass(frozen=True, slots=True)
class RecoveryDashboardSummary:
    currency: str
    revenue_at_risk_minor: int
    verified_recovered_minor: int
    duplicate_collection_prevented_minor: int
    active_incident_revenue_at_risk_minor: int
    active_case_count: int
    recovered_case_count: int
    pending_outcome_count: int
    open_incident_count: int


def normalize_dashboard_currency(currency: str) -> str:
    normalized_currency = currency.strip().upper()

    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        raise ValueError(
            "Dashboard currency must be a three-letter alphabetic code",
        )

    return normalized_currency


async def load_recovery_dashboard_summary(
    session: AsyncSession,
    *,
    currency: str,
) -> RecoveryDashboardSummary:
    normalized_currency = normalize_dashboard_currency(currency)

    case_result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            RecoveryCase.status.in_(ACTIVE_CASE_STATUSES),
                            RecoveryCase.amount_minor,
                        ),
                        else_=0,
                    ),
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (RecoveryCase.status.in_(ACTIVE_CASE_STATUSES), 1),
                        else_=0,
                    ),
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            RecoveryCase.status == RecoveryCaseStatus.RECOVERED.value,
                            1,
                        ),
                        else_=0,
                    ),
                ),
                0,
            ),
        ).where(
            RecoveryCase.currency == normalized_currency,
        ),
    )
    (
        revenue_at_risk_minor,
        active_case_count,
        recovered_case_count,
    ) = case_result.one()

    outcome_result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    RecoveryOutcome.gross_recovered_minor - RecoveryOutcome.reversed_minor,
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    RecoveryOutcome.duplicate_collection_prevented_minor,
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            RecoveryOutcome.status.in_(
                                PENDING_OUTCOME_STATUSES,
                            ),
                            1,
                        ),
                        else_=0,
                    ),
                ),
                0,
            ),
        ).where(
            RecoveryOutcome.currency == normalized_currency,
        ),
    )
    (
        verified_recovered_minor,
        duplicate_collection_prevented_minor,
        pending_outcome_count,
    ) = outcome_result.one()

    incident_result = await session.execute(
        select(
            func.coalesce(
                func.sum(RevenueIncident.revenue_at_risk_minor),
                0,
            ),
            func.count(RevenueIncident.id),
        ).where(
            RevenueIncident.currency == normalized_currency,
            RevenueIncident.status.in_(ACTIVE_INCIDENT_STATUSES),
        ),
    )
    (
        active_incident_revenue_at_risk_minor,
        open_incident_count,
    ) = incident_result.one()

    return RecoveryDashboardSummary(
        currency=normalized_currency,
        revenue_at_risk_minor=int(revenue_at_risk_minor),
        verified_recovered_minor=int(verified_recovered_minor),
        duplicate_collection_prevented_minor=int(
            duplicate_collection_prevented_minor,
        ),
        active_incident_revenue_at_risk_minor=int(
            active_incident_revenue_at_risk_minor,
        ),
        active_case_count=int(active_case_count),
        recovered_case_count=int(recovered_case_count),
        pending_outcome_count=int(pending_outcome_count),
        open_incident_count=int(open_incident_count),
    )
