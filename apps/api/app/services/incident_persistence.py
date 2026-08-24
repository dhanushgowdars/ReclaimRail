from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import (
    IncidentDetectionObservation,
    RevenueIncident,
    RevenueIncidentStatus,
)
from app.domain.incidents import (
    BaselineProfile,
    IncidentDetectionDecision,
    IncidentDetectionOutcome,
    IncidentSeverity,
    PaymentWindowMetrics,
    build_incident_fingerprint,
)

DEFAULT_DETECTOR_VERSION: Final = "robust-mad-v1"

ACTIVE_INCIDENT_STATUSES: Final[tuple[str, ...]] = (
    RevenueIncidentStatus.OPEN.value,
    RevenueIncidentStatus.INVESTIGATING.value,
    RevenueIncidentStatus.MITIGATING.value,
)

SEVERITY_RANK: Final[dict[str, int]] = {
    IncidentSeverity.LOW.value: 1,
    IncidentSeverity.MEDIUM.value: 2,
    IncidentSeverity.HIGH.value: 3,
    IncidentSeverity.CRITICAL.value: 4,
}


class IncidentPersistenceInvariantError(ValueError):
    """Raised when detector inputs disagree before persistence."""


@dataclass(frozen=True, slots=True)
class IncidentPersistenceResult:
    observation_id: UUID
    incident_id: UUID | None
    outcome: IncidentDetectionOutcome
    created_incident: bool
    updated_incident: bool
    duplicate_observation: bool


def normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()

    if len(normalized) != 3 or not normalized.isalpha():
        raise IncidentPersistenceInvariantError(
            "Currency must be a three-letter alphabetic code",
        )

    return normalized


def normalize_detector_version(detector_version: str) -> str:
    normalized = detector_version.strip()

    if not normalized:
        raise IncidentPersistenceInvariantError(
            "Detector version cannot be empty",
        )

    if len(normalized) > 32:
        raise IncidentPersistenceInvariantError(
            "Detector version cannot exceed 32 characters",
        )

    return normalized


def require_timezone_aware(
    value: datetime,
    field_name: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IncidentPersistenceInvariantError(
            f"{field_name} must be timezone-aware",
        )


def validate_detection_context(
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    decision: IncidentDetectionDecision,
) -> None:
    metrics_fingerprint = build_incident_fingerprint(
        metrics.scope,
        metrics.dimension_value,
    )
    baseline_fingerprint = build_incident_fingerprint(
        baseline.scope,
        baseline.dimension_value,
    )

    if metrics_fingerprint != baseline_fingerprint:
        raise IncidentPersistenceInvariantError(
            "Metrics and baseline dimensions do not match",
        )

    if decision.fingerprint != metrics_fingerprint:
        raise IncidentPersistenceInvariantError(
            "Decision fingerprint does not match metrics",
        )

    if decision.scope != metrics.scope:
        raise IncidentPersistenceInvariantError(
            "Decision scope does not match metrics",
        )

    if (
        build_incident_fingerprint(
            decision.scope,
            decision.dimension_value,
        )
        != metrics_fingerprint
    ):
        raise IncidentPersistenceInvariantError(
            "Decision dimension does not match metrics",
        )

    if decision.revenue_at_risk_minor != metrics.failed_amount_minor:
        raise IncidentPersistenceInvariantError(
            "Decision revenue at risk does not match failed amount",
        )

    if decision.outcome == IncidentDetectionOutcome.INCIDENT and decision.severity is None:
        raise IncidentPersistenceInvariantError(
            "Incident decision requires a severity",
        )

    if decision.outcome != IncidentDetectionOutcome.INCIDENT and decision.severity is not None:
        raise IncidentPersistenceInvariantError(
            "Non-incident decision cannot have a severity",
        )


def build_detection_evidence(
    *,
    detector_run_id: UUID,
    detector_version: str,
    currency: str,
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    decision: IncidentDetectionDecision,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "detector": {
            "run_id": str(detector_run_id),
            "version": detector_version,
        },
        "dimension": {
            "scope": decision.scope.value,
            "value": decision.dimension_value,
            "fingerprint": decision.fingerprint,
            "currency": currency,
        },
        "window": {
            "start": metrics.window_start.isoformat(),
            "end": metrics.window_end.isoformat(),
            "total_attempts": metrics.total_attempts,
            "failed_attempts": metrics.failed_attempts,
            "total_amount_minor": metrics.total_amount_minor,
            "failed_amount_minor": metrics.failed_amount_minor,
        },
        "baseline": {
            "window_count": baseline.window_count,
            "median_failure_rate": baseline.median_failure_rate,
            "mad_failure_rate": baseline.mad_failure_rate,
            "median_failed_amount_minor": (baseline.median_failed_amount_minor),
        },
        "decision": {
            "outcome": decision.outcome.value,
            "severity": (decision.severity.value if decision.severity is not None else None),
            "reason_codes": [reason.value for reason in decision.reason_codes],
            "failure_rate": decision.failure_rate,
            "baseline_failure_rate": (decision.baseline_failure_rate),
            "absolute_uplift": decision.absolute_uplift,
            "rate_multiplier": decision.rate_multiplier,
            "robust_z_score": decision.robust_z_score,
            "revenue_at_risk_minor": (decision.revenue_at_risk_minor),
            "confidence": decision.confidence,
        },
    }

    return evidence


async def acquire_incident_lock(
    session: AsyncSession,
    *,
    fingerprint: str,
    currency: str,
) -> None:
    lock_key = f"reclaimrail:revenue-incident:{fingerprint}:{currency}"

    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(
                    lock_key,
                    0,
                ),
            ),
        ),
    )


async def find_existing_observation(
    session: AsyncSession,
    *,
    fingerprint: str,
    currency: str,
    window_start: datetime,
    window_end: datetime,
    detector_version: str,
) -> IncidentDetectionObservation | None:
    result = await session.execute(
        select(IncidentDetectionObservation).where(
            IncidentDetectionObservation.fingerprint == fingerprint,
            IncidentDetectionObservation.currency == currency,
            IncidentDetectionObservation.window_start == window_start,
            IncidentDetectionObservation.window_end == window_end,
            IncidentDetectionObservation.detector_version == detector_version,
        ),
    )

    return result.scalar_one_or_none()


async def find_active_incident(
    session: AsyncSession,
    *,
    fingerprint: str,
    currency: str,
) -> RevenueIncident | None:
    result = await session.execute(
        select(RevenueIncident)
        .where(
            RevenueIncident.fingerprint == fingerprint,
            RevenueIncident.currency == currency,
            RevenueIncident.status.in_(
                ACTIVE_INCIDENT_STATUSES,
            ),
        )
        .order_by(
            RevenueIncident.first_detected_at.asc(),
        )
        .limit(1)
        .with_for_update(),
    )

    return result.scalar_one_or_none()


def choose_peak_severity(
    current_severity: str,
    incoming_severity: IncidentSeverity,
) -> str:
    current_rank = SEVERITY_RANK.get(
        current_severity,
        0,
    )
    incoming_rank = SEVERITY_RANK[incoming_severity.value]

    if incoming_rank > current_rank:
        return incoming_severity.value

    return current_severity


def create_revenue_incident(
    *,
    currency: str,
    detected_at: datetime,
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    decision: IncidentDetectionDecision,
    evidence: dict[str, object],
) -> RevenueIncident:
    if decision.severity is None:
        raise IncidentPersistenceInvariantError(
            "Incident creation requires a severity",
        )

    return RevenueIncident(
        id=uuid4(),
        fingerprint=decision.fingerprint,
        scope=decision.scope.value,
        dimension_value=decision.dimension_value,
        currency=currency,
        status=RevenueIncidentStatus.OPEN.value,
        severity=decision.severity.value,
        first_detected_at=detected_at,
        last_detected_at=detected_at,
        current_window_start=metrics.window_start,
        current_window_end=metrics.window_end,
        total_attempts=metrics.total_attempts,
        failed_attempts=metrics.failed_attempts,
        total_amount_minor=metrics.total_amount_minor,
        revenue_at_risk_minor=(decision.revenue_at_risk_minor),
        failure_rate=decision.failure_rate,
        baseline_failure_rate=(decision.baseline_failure_rate),
        absolute_uplift=decision.absolute_uplift,
        rate_multiplier=decision.rate_multiplier,
        robust_z_score=decision.robust_z_score,
        confidence=decision.confidence,
        occurrence_count=1,
        reason_codes=[reason.value for reason in decision.reason_codes],
        evidence=dict(evidence),
        resolved_at=None,
        resolution_reason=None,
        created_at=detected_at,
        updated_at=detected_at,
    )


def update_revenue_incident(
    incident: RevenueIncident,
    *,
    detected_at: datetime,
    metrics: PaymentWindowMetrics,
    decision: IncidentDetectionDecision,
    evidence: dict[str, object],
) -> None:
    if decision.severity is None:
        raise IncidentPersistenceInvariantError(
            "Incident update requires a severity",
        )

    incident.last_detected_at = max(
        incident.last_detected_at,
        detected_at,
    )
    incident.occurrence_count += 1
    incident.severity = choose_peak_severity(
        incident.severity,
        decision.severity,
    )
    incident.updated_at = detected_at

    if metrics.window_end < incident.current_window_end:
        return

    incident.current_window_start = metrics.window_start
    incident.current_window_end = metrics.window_end
    incident.total_attempts = metrics.total_attempts
    incident.failed_attempts = metrics.failed_attempts
    incident.total_amount_minor = metrics.total_amount_minor
    incident.revenue_at_risk_minor = decision.revenue_at_risk_minor
    incident.failure_rate = decision.failure_rate
    incident.baseline_failure_rate = decision.baseline_failure_rate
    incident.absolute_uplift = decision.absolute_uplift
    incident.rate_multiplier = decision.rate_multiplier
    incident.robust_z_score = decision.robust_z_score
    incident.confidence = decision.confidence
    incident.reason_codes = [reason.value for reason in decision.reason_codes]
    incident.evidence = dict(evidence)


def create_detection_observation(
    *,
    detector_run_id: UUID,
    detector_version: str,
    incident_id: UUID | None,
    currency: str,
    detected_at: datetime,
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    decision: IncidentDetectionDecision,
    evidence: dict[str, object],
) -> IncidentDetectionObservation:
    return IncidentDetectionObservation(
        id=uuid4(),
        detector_run_id=detector_run_id,
        incident_id=incident_id,
        detector_version=detector_version,
        fingerprint=decision.fingerprint,
        scope=decision.scope.value,
        dimension_value=decision.dimension_value,
        currency=currency,
        outcome=decision.outcome.value,
        severity=(decision.severity.value if decision.severity is not None else None),
        window_start=metrics.window_start,
        window_end=metrics.window_end,
        baseline_window_count=baseline.window_count,
        total_attempts=metrics.total_attempts,
        failed_attempts=metrics.failed_attempts,
        total_amount_minor=metrics.total_amount_minor,
        revenue_at_risk_minor=(decision.revenue_at_risk_minor),
        failure_rate=decision.failure_rate,
        baseline_failure_rate=(decision.baseline_failure_rate),
        mad_failure_rate=round(
            baseline.mad_failure_rate,
            6,
        ),
        absolute_uplift=decision.absolute_uplift,
        rate_multiplier=decision.rate_multiplier,
        robust_z_score=decision.robust_z_score,
        confidence=decision.confidence,
        reason_codes=[reason.value for reason in decision.reason_codes],
        evidence=dict(evidence),
        detected_at=detected_at,
        created_at=detected_at,
    )


async def persist_incident_detection(
    session: AsyncSession,
    *,
    detector_run_id: UUID,
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    decision: IncidentDetectionDecision,
    currency: str = "INR",
    detector_version: str = DEFAULT_DETECTOR_VERSION,
    detected_at: datetime | None = None,
) -> IncidentPersistenceResult:
    validate_detection_context(
        metrics,
        baseline,
        decision,
    )

    normalized_currency = normalize_currency(currency)
    normalized_detector_version = normalize_detector_version(
        detector_version,
    )
    effective_detected_at = detected_at if detected_at is not None else datetime.now(UTC)

    require_timezone_aware(
        effective_detected_at,
        "Detected at",
    )

    await acquire_incident_lock(
        session,
        fingerprint=decision.fingerprint,
        currency=normalized_currency,
    )

    existing_observation = await find_existing_observation(
        session,
        fingerprint=decision.fingerprint,
        currency=normalized_currency,
        window_start=metrics.window_start,
        window_end=metrics.window_end,
        detector_version=normalized_detector_version,
    )

    if existing_observation is not None:
        return IncidentPersistenceResult(
            observation_id=existing_observation.id,
            incident_id=existing_observation.incident_id,
            outcome=IncidentDetectionOutcome(
                existing_observation.outcome,
            ),
            created_incident=False,
            updated_incident=False,
            duplicate_observation=True,
        )

    evidence = build_detection_evidence(
        detector_run_id=detector_run_id,
        detector_version=normalized_detector_version,
        currency=normalized_currency,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
    )

    active_incident = await find_active_incident(
        session,
        fingerprint=decision.fingerprint,
        currency=normalized_currency,
    )

    created_incident = False
    updated_incident = False

    if decision.outcome == IncidentDetectionOutcome.INCIDENT:
        if active_incident is None:
            active_incident = create_revenue_incident(
                currency=normalized_currency,
                detected_at=effective_detected_at,
                metrics=metrics,
                baseline=baseline,
                decision=decision,
                evidence=evidence,
            )
            session.add(active_incident)

            # Persist the parent before inserting its FK observation.
            await session.flush([active_incident])

            created_incident = True
        else:
            update_revenue_incident(
                active_incident,
                detected_at=effective_detected_at,
                metrics=metrics,
                decision=decision,
                evidence=evidence,
            )
            updated_incident = True

    observation = create_detection_observation(
        detector_run_id=detector_run_id,
        detector_version=normalized_detector_version,
        incident_id=(active_incident.id if active_incident is not None else None),
        currency=normalized_currency,
        detected_at=effective_detected_at,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        evidence=evidence,
    )
    session.add(observation)

    await session.flush()

    return IncidentPersistenceResult(
        observation_id=observation.id,
        incident_id=observation.incident_id,
        outcome=decision.outcome,
        created_incident=created_incident,
        updated_incident=updated_incident,
        duplicate_observation=False,
    )
