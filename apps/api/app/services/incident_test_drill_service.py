"""Explicit, non-provider Test Mode incident drills for operational demos."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import RevenueIncident, RevenueIncidentStatus
from app.domain.incidents import IncidentSeverity


async def create_test_mode_incident_drill(
    session: AsyncSession,
    *,
    payment_method: str,
    currency: str,
    severity: IncidentSeverity,
    duration_minutes: int,
    now: datetime | None = None,
) -> RevenueIncident:
    """Create a clearly-labelled synthetic drill; it never represents provider truth."""
    started_at = now or datetime.now(UTC)
    expires_at = started_at + timedelta(minutes=duration_minutes)
    incident = RevenueIncident(
        fingerprint=f"test-mode-drill:{payment_method}:{uuid4()}",
        scope="payment_method",
        dimension_value=payment_method,
        currency=currency.upper(),
        status=RevenueIncidentStatus.OPEN.value,
        severity=severity.value,
        first_detected_at=started_at,
        last_detected_at=started_at,
        current_window_start=started_at,
        current_window_end=expires_at,
        total_attempts=10,
        failed_attempts=8,
        total_amount_minor=100_000,
        revenue_at_risk_minor=80_000,
        failure_rate=0.8,
        baseline_failure_rate=0.05,
        absolute_uplift=0.75,
        rate_multiplier=16.0,
        robust_z_score=8.0,
        confidence=1.0,
        occurrence_count=1,
        reason_codes=["test_mode_incident_drill"],
        evidence={
            "test_mode_drill": {
                "label": "TEST MODE INCIDENT DRILL — not provider evidence",
                "expires_at": expires_at.isoformat(),
            }
        },
    )
    session.add(incident)
    await session.flush()
    return incident
