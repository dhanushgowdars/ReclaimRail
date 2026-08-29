"""Current payment-rail incident context for bounded recovery decisions.

An incident can begin after a recovery case is opened.  Provider actions must
therefore re-check the active rail state rather than relying only on the
incident identifier captured when the case was created.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.incident import RevenueIncident, RevenueIncidentStatus
from app.domain.incidents import IncidentSeverity

ACTIVE_INCIDENT_STATUSES = frozenset(
    {
        RevenueIncidentStatus.OPEN.value,
        RevenueIncidentStatus.INVESTIGATING.value,
        RevenueIncidentStatus.MITIGATING.value,
    },
)


@dataclass(frozen=True, slots=True)
class ActiveRecoveryIncidentContext:
    incident_id: UUID
    severity: IncidentSeverity
    scope: str
    dimension_value: str


def _severity_rank() -> ColumnElement[int]:
    return case(
        (RevenueIncident.severity == IncidentSeverity.CRITICAL.value, 4),
        (RevenueIncident.severity == IncidentSeverity.HIGH.value, 3),
        (RevenueIncident.severity == IncidentSeverity.MEDIUM.value, 2),
        else_=1,
    )


async def load_active_recovery_incident_context(
    session: AsyncSession,
    *,
    source_incident_id: UUID | None,
    currency: str,
    payment_method: str | None,
) -> ActiveRecoveryIncidentContext | None:
    """Return the strongest active incident relevant to this recovery case.

    A stored source incident is retained as evidence, while global and
    payment-method incidents are evaluated dynamically for every decision.
    """

    dynamic_match = RevenueIncident.scope == "global"
    if payment_method is not None:
        dynamic_match = or_(
            dynamic_match,
            (RevenueIncident.scope == "payment_method")
            & (RevenueIncident.dimension_value == payment_method),
        )
    relevant_match = dynamic_match
    if source_incident_id is not None:
        relevant_match = or_(RevenueIncident.id == source_incident_id, dynamic_match)

    result = await session.execute(
        select(RevenueIncident)
        .where(
            RevenueIncident.status.in_(ACTIVE_INCIDENT_STATUSES),
            RevenueIncident.currency == currency,
            RevenueIncident.current_window_end >= datetime.now(UTC),
            relevant_match,
        )
        .order_by(desc(_severity_rank()), desc(RevenueIncident.last_detected_at))
        .limit(1),
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        return None

    return ActiveRecoveryIncidentContext(
        incident_id=incident.id,
        severity=IncidentSeverity(incident.severity),
        scope=incident.scope,
        dimension_value=incident.dimension_value,
    )
