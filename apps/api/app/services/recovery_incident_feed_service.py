from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import RevenueIncident, RevenueIncidentStatus
from app.services.recovery_dashboard_service import normalize_dashboard_currency

MAX_ACTIVE_INCIDENTS: Final = 25
ACTIVE_INCIDENT_STATUSES: Final = (
    RevenueIncidentStatus.OPEN.value,
    RevenueIncidentStatus.INVESTIGATING.value,
    RevenueIncidentStatus.MITIGATING.value,
)


@dataclass(frozen=True, slots=True)
class RecoveryIncidentFeedItem:
    incident_id: UUID
    status: str
    severity: str
    scope: str
    dimension_value: str
    currency: str
    revenue_at_risk_minor: int
    failure_rate: float
    baseline_failure_rate: float
    absolute_uplift: float
    rate_multiplier: float | None
    confidence: float
    occurrence_count: int
    reason_codes: tuple[str, ...]
    first_detected_at: datetime
    last_detected_at: datetime


def build_recovery_incident_feed_item(
    incident: RevenueIncident,
) -> RecoveryIncidentFeedItem:
    return RecoveryIncidentFeedItem(
        incident_id=incident.id,
        status=incident.status,
        severity=incident.severity,
        scope=incident.scope,
        dimension_value=incident.dimension_value,
        currency=incident.currency,
        revenue_at_risk_minor=incident.revenue_at_risk_minor,
        failure_rate=incident.failure_rate,
        baseline_failure_rate=incident.baseline_failure_rate,
        absolute_uplift=incident.absolute_uplift,
        rate_multiplier=incident.rate_multiplier,
        confidence=incident.confidence,
        occurrence_count=incident.occurrence_count,
        reason_codes=tuple(incident.reason_codes),
        first_detected_at=incident.first_detected_at,
        last_detected_at=incident.last_detected_at,
    )


async def load_active_recovery_incidents(
    session: AsyncSession,
    *,
    currency: str,
    limit: int = 5,
) -> tuple[RecoveryIncidentFeedItem, ...]:
    normalized_currency = normalize_dashboard_currency(currency)

    if limit < 1 or limit > MAX_ACTIVE_INCIDENTS:
        raise ValueError(
            f"Active incident limit must be between 1 and {MAX_ACTIVE_INCIDENTS}",
        )

    severity_rank = case(
        {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        },
        value=RevenueIncident.severity,
        else_=0,
    )
    result = await session.execute(
        select(RevenueIncident)
        .where(
            RevenueIncident.currency == normalized_currency,
            RevenueIncident.status.in_(ACTIVE_INCIDENT_STATUSES),
            RevenueIncident.current_window_end >= datetime.now(UTC),
        )
        .order_by(
            severity_rank.desc(),
            RevenueIncident.last_detected_at.desc(),
            RevenueIncident.id,
        )
        .limit(limit),
    )

    return tuple(build_recovery_incident_feed_item(incident) for incident in result.scalars().all())
