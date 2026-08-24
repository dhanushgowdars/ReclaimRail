from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
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
    IncidentScope,
    IncidentSeverity,
    PaymentWindowMetrics,
    build_baseline_profile,
    build_incident_fingerprint,
    detect_payment_degradation,
)
from app.services.incident_persistence import (
    IncidentPersistenceInvariantError,
    normalize_currency,
    persist_incident_detection,
)

BASE_TIME = datetime(
    2026,
    8,
    24,
    10,
    0,
    tzinfo=UTC,
)
DETECTED_AT = BASE_TIME + timedelta(hours=4)

RUN_ID = UUID("10000000-0000-0000-0000-000000000001")
INCIDENT_ID = UUID("20000000-0000-0000-0000-000000000001")
OBSERVATION_ID = UUID(
    "30000000-0000-0000-0000-000000000001",
)


def create_window(
    index: int,
    *,
    total_attempts: int,
    failed_attempts: int,
    failed_amount_minor: int,
    total_amount_minor: int = 5_000_000,
    dimension_value: str = "upi",
) -> PaymentWindowMetrics:
    window_start = BASE_TIME + timedelta(
        minutes=index * 5,
    )

    return PaymentWindowMetrics(
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value=dimension_value,
        window_start=window_start,
        window_end=window_start + timedelta(minutes=5),
        total_attempts=total_attempts,
        failed_attempts=failed_attempts,
        total_amount_minor=total_amount_minor,
        failed_amount_minor=failed_amount_minor,
    )


def create_baseline() -> BaselineProfile:
    failed_counts = [
        4,
        5,
        6,
        5,
        5,
        4,
        6,
        5,
    ]

    windows = [
        create_window(
            index,
            total_attempts=100,
            failed_attempts=failed_count,
            failed_amount_minor=failed_count * 10_000,
        )
        for index, failed_count in enumerate(
            failed_counts,
        )
    ]

    return build_baseline_profile(windows)


def create_detection(
    *,
    index: int = 20,
    total_attempts: int = 100,
    failed_attempts: int = 40,
    failed_amount_minor: int = 800_000,
    total_amount_minor: int = 5_000_000,
) -> tuple[
    PaymentWindowMetrics,
    BaselineProfile,
    IncidentDetectionDecision,
]:
    baseline = create_baseline()
    metrics = create_window(
        index,
        total_attempts=total_attempts,
        failed_attempts=failed_attempts,
        failed_amount_minor=failed_amount_minor,
        total_amount_minor=total_amount_minor,
    )
    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    return metrics, baseline, decision


def create_query_result(
    value: object | None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def create_session(
    *execute_results: MagicMock,
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = list(execute_results)
    return session


def create_active_incident(
    *,
    window_index: int = 10,
    severity: str = IncidentSeverity.MEDIUM.value,
    total_amount_minor: int = 5_000_000,
) -> RevenueIncident:
    window_start = BASE_TIME + timedelta(
        minutes=window_index * 5,
    )
    window_end = window_start + timedelta(minutes=5)

    return RevenueIncident(
        id=INCIDENT_ID,
        fingerprint=build_incident_fingerprint(
            IncidentScope.PAYMENT_METHOD,
            "upi",
        ),
        scope=IncidentScope.PAYMENT_METHOD.value,
        dimension_value="upi",
        currency="INR",
        status=RevenueIncidentStatus.OPEN.value,
        severity=severity,
        first_detected_at=BASE_TIME,
        last_detected_at=window_end,
        current_window_start=window_start,
        current_window_end=window_end,
        total_attempts=100,
        failed_attempts=25,
        total_amount_minor=total_amount_minor,
        revenue_at_risk_minor=500_000,
        failure_rate=0.25,
        baseline_failure_rate=0.05,
        absolute_uplift=0.20,
        rate_multiplier=5.0,
        robust_z_score=8.0,
        confidence=0.75,
        occurrence_count=1,
        reason_codes=[
            "failure_rate_threshold",
            "baseline_uplift",
        ],
        evidence={
            "source": "existing",
        },
        resolved_at=None,
        resolution_reason=None,
        created_at=BASE_TIME,
        updated_at=window_end,
    )


def test_normalizes_currency() -> None:
    assert normalize_currency(" inr ") == "INR"

    with pytest.raises(
        IncidentPersistenceInvariantError,
        match="three-letter",
    ):
        normalize_currency("rupees")


@pytest.mark.asyncio
async def test_creates_incident_and_observation() -> None:
    metrics, baseline, decision = create_detection()

    assert decision.outcome is IncidentDetectionOutcome.INCIDENT

    session = create_session(
        MagicMock(),
        create_query_result(None),
        create_query_result(None),
    )

    result = await persist_incident_detection(
        session,
        detector_run_id=RUN_ID,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        detected_at=DETECTED_AT,
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]
    incidents = [item for item in added_objects if isinstance(item, RevenueIncident)]
    observations = [
        item
        for item in added_objects
        if isinstance(
            item,
            IncidentDetectionObservation,
        )
    ]

    assert result.outcome is IncidentDetectionOutcome.INCIDENT
    assert result.created_incident is True
    assert result.updated_incident is False
    assert result.duplicate_observation is False

    assert len(incidents) == 1
    assert len(observations) == 1

    incident = incidents[0]
    observation = observations[0]

    assert result.incident_id == incident.id
    assert result.observation_id == observation.id
    assert observation.incident_id == incident.id

    assert incident.status == RevenueIncidentStatus.OPEN.value
    assert incident.severity == IncidentSeverity.HIGH.value
    assert incident.occurrence_count == 1
    assert incident.revenue_at_risk_minor == 800_000

    assert observation.outcome == (IncidentDetectionOutcome.INCIDENT.value)
    assert observation.currency == "INR"
    assert observation.detector_run_id == RUN_ID
    assert observation.evidence["detector"] == {
        "run_id": str(RUN_ID),
        "version": "robust-mad-v1",
    }

    assert session.execute.await_count == 3
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_replayed_window_returns_existing_observation() -> None:
    metrics, baseline, decision = create_detection()

    existing_observation = IncidentDetectionObservation(
        id=OBSERVATION_ID,
        incident_id=INCIDENT_ID,
        outcome=IncidentDetectionOutcome.INCIDENT.value,
    )

    session = create_session(
        MagicMock(),
        create_query_result(existing_observation),
    )

    result = await persist_incident_detection(
        session,
        detector_run_id=RUN_ID,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        detected_at=DETECTED_AT,
    )

    assert result.observation_id == OBSERVATION_ID
    assert result.incident_id == INCIDENT_ID
    assert result.duplicate_observation is True
    assert result.created_incident is False
    assert result.updated_incident is False

    assert session.execute.await_count == 2
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_updates_existing_active_incident() -> None:
    metrics, baseline, decision = create_detection(
        index=20,
        failed_attempts=40,
        failed_amount_minor=800_000,
    )
    active_incident = create_active_incident(
        severity=IncidentSeverity.MEDIUM.value,
    )

    session = create_session(
        MagicMock(),
        create_query_result(None),
        create_query_result(active_incident),
    )

    result = await persist_incident_detection(
        session,
        detector_run_id=RUN_ID,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        detected_at=DETECTED_AT,
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]

    assert result.created_incident is False
    assert result.updated_incident is True
    assert result.incident_id == INCIDENT_ID

    assert active_incident.occurrence_count == 2
    assert active_incident.severity == (IncidentSeverity.HIGH.value)
    assert active_incident.current_window_start == (metrics.window_start)
    assert active_incident.current_window_end == (metrics.window_end)
    assert active_incident.revenue_at_risk_minor == 800_000

    assert len(added_objects) == 1
    observation = added_objects[0]
    assert isinstance(
        observation,
        IncidentDetectionObservation,
    )
    assert observation.incident_id == INCIDENT_ID

    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_out_of_order_window_does_not_regress_projection() -> None:
    metrics, baseline, decision = create_detection(
        index=20,
        failed_attempts=40,
        failed_amount_minor=800_000,
    )
    active_incident = create_active_incident(
        window_index=30,
        severity=IncidentSeverity.HIGH.value,
        total_amount_minor=9_000_000,
    )

    original_window_start = active_incident.current_window_start
    original_window_end = active_incident.current_window_end
    original_total_amount = active_incident.total_amount_minor
    original_evidence = dict(active_incident.evidence)

    session = create_session(
        MagicMock(),
        create_query_result(None),
        create_query_result(active_incident),
    )

    result = await persist_incident_detection(
        session,
        detector_run_id=RUN_ID,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        detected_at=DETECTED_AT,
    )

    assert result.updated_incident is True
    assert active_incident.occurrence_count == 2

    assert active_incident.current_window_start == (original_window_start)
    assert active_incident.current_window_end == (original_window_end)
    assert active_incident.total_amount_minor == (original_total_amount)
    assert active_incident.evidence == original_evidence


@pytest.mark.asyncio
async def test_normal_observation_links_to_active_incident() -> None:
    metrics, baseline, decision = create_detection(
        failed_attempts=7,
        failed_amount_minor=70_000,
    )
    active_incident = create_active_incident(
        severity=IncidentSeverity.HIGH.value,
    )

    assert decision.outcome is IncidentDetectionOutcome.NORMAL

    session = create_session(
        MagicMock(),
        create_query_result(None),
        create_query_result(active_incident),
    )

    result = await persist_incident_detection(
        session,
        detector_run_id=RUN_ID,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        detected_at=DETECTED_AT,
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]

    assert result.outcome is IncidentDetectionOutcome.NORMAL
    assert result.incident_id == INCIDENT_ID
    assert result.created_incident is False
    assert result.updated_incident is False
    assert active_incident.occurrence_count == 1

    assert len(added_objects) == 1
    observation = added_objects[0]
    assert isinstance(
        observation,
        IncidentDetectionObservation,
    )
    assert observation.incident_id == INCIDENT_ID
    assert observation.severity is None


@pytest.mark.asyncio
async def test_insufficient_data_is_audited_without_incident() -> None:
    metrics, baseline, decision = create_detection(
        total_attempts=10,
        failed_attempts=5,
        failed_amount_minor=100_000,
    )

    assert decision.outcome is (IncidentDetectionOutcome.INSUFFICIENT_DATA)

    session = create_session(
        MagicMock(),
        create_query_result(None),
        create_query_result(None),
    )

    result = await persist_incident_detection(
        session,
        detector_run_id=RUN_ID,
        metrics=metrics,
        baseline=baseline,
        decision=decision,
        detected_at=DETECTED_AT,
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]

    assert result.incident_id is None
    assert result.created_incident is False
    assert result.updated_incident is False

    assert len(added_objects) == 1
    observation = added_objects[0]
    assert isinstance(
        observation,
        IncidentDetectionObservation,
    )
    assert observation.outcome == (IncidentDetectionOutcome.INSUFFICIENT_DATA.value)
    assert observation.incident_id is None
    assert observation.severity is None


@pytest.mark.asyncio
async def test_rejects_mismatched_decision_before_database() -> None:
    metrics, baseline, decision = create_detection()
    invalid_decision = replace(
        decision,
        fingerprint="payment_degradation:payment_method:card",
    )
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(
        IncidentPersistenceInvariantError,
        match="fingerprint",
    ):
        await persist_incident_detection(
            session,
            detector_run_id=RUN_ID,
            metrics=metrics,
            baseline=baseline,
            decision=invalid_decision,
            detected_at=DETECTED_AT,
        )

    session.execute.assert_not_awaited()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
