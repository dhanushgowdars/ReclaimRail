from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.incidents import (
    BaselineProfile,
    IncidentDetectionDecision,
    IncidentDetectorPolicy,
    PaymentWindowMetrics,
    build_baseline_profile,
    detect_payment_degradation,
)
from app.domain.incidents.detector import (
    DEFAULT_INCIDENT_DETECTOR_POLICY,
)
from app.services.incident_persistence import (
    IncidentPersistenceResult,
    persist_incident_detection,
)
from app.services.incident_window_aggregator import (
    DEFAULT_BASELINE_WINDOW_COUNT,
    DEFAULT_WINDOW_SIZE,
    load_payment_method_window_series,
    resolve_latest_closed_window_end,
)


@dataclass(frozen=True, slots=True)
class IncidentDetectionRunResult:
    detector_run_id: UUID
    payment_method: str
    currency: str
    current_window_end: datetime
    metrics: PaymentWindowMetrics
    baseline: BaselineProfile
    decision: IncidentDetectionDecision
    persistence: IncidentPersistenceResult


async def run_payment_method_incident_detection(
    session: AsyncSession,
    *,
    payment_method: str,
    currency: str,
    reference_time: datetime,
    detector_run_id: UUID | None = None,
    detected_at: datetime | None = None,
    window_size: timedelta = DEFAULT_WINDOW_SIZE,
    baseline_window_count: int = DEFAULT_BASELINE_WINDOW_COUNT,
    policy: IncidentDetectorPolicy = (DEFAULT_INCIDENT_DETECTOR_POLICY),
) -> IncidentDetectionRunResult:
    normalized_method = payment_method.strip().casefold()
    normalized_currency = currency.strip().upper()

    if not normalized_method:
        raise ValueError("Payment method cannot be empty")

    if len(normalized_currency) != 3:
        raise ValueError("Currency must be a three-letter code")

    current_window_end = resolve_latest_closed_window_end(
        reference_time,
        window_size,
    )

    series = await load_payment_method_window_series(
        session,
        payment_method=normalized_method,
        currency=normalized_currency,
        current_window_end=current_window_end,
        window_size=window_size,
        baseline_window_count=baseline_window_count,
    )

    baseline = build_baseline_profile(
        series.baseline_windows,
    )

    decision = detect_payment_degradation(
        series.current_window,
        baseline,
        policy,
    )

    resolved_run_id = detector_run_id or uuid4()
    resolved_detected_at = detected_at or reference_time

    persistence = await persist_incident_detection(
        session,
        detector_run_id=resolved_run_id,
        metrics=series.current_window,
        baseline=baseline,
        decision=decision,
        currency=normalized_currency,
        detected_at=resolved_detected_at,
    )

    return IncidentDetectionRunResult(
        detector_run_id=resolved_run_id,
        payment_method=normalized_method,
        currency=normalized_currency,
        current_window_end=current_window_end,
        metrics=series.current_window,
        baseline=baseline,
        decision=decision,
        persistence=persistence,
    )
