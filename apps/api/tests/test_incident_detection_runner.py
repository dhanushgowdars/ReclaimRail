from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.incidents import (
    IncidentDetectionOutcome,
    IncidentScope,
    PaymentWindowMetrics,
)
from app.services import incident_detection_runner
from app.services.incident_detection_runner import (
    run_payment_method_incident_detection,
)
from app.services.incident_persistence import (
    IncidentPersistenceResult,
)
from app.services.incident_window_aggregator import (
    PaymentWindowSeries,
)

REFERENCE_TIME = datetime(
    2026,
    8,
    24,
    10,
    7,
    tzinfo=UTC,
)

CURRENT_WINDOW_END = datetime(
    2026,
    8,
    24,
    10,
    5,
    tzinfo=UTC,
)


def create_window(
    window_start: datetime,
    *,
    failed_attempts: int,
    failed_amount_minor: int,
) -> PaymentWindowMetrics:
    return PaymentWindowMetrics(
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value="upi",
        window_start=window_start,
        window_end=window_start + timedelta(minutes=5),
        total_attempts=100,
        failed_attempts=failed_attempts,
        total_amount_minor=2_000_000,
        failed_amount_minor=failed_amount_minor,
    )


def create_series() -> PaymentWindowSeries:
    baseline_start = CURRENT_WINDOW_END - timedelta(
        minutes=35,
    )

    baseline_windows = tuple(
        create_window(
            baseline_start + timedelta(minutes=index * 5),
            failed_attempts=failed_count,
            failed_amount_minor=failed_count * 10_000,
        )
        for index, failed_count in enumerate(
            [4, 5, 6, 5, 4, 6],
        )
    )

    current_window = create_window(
        CURRENT_WINDOW_END - timedelta(minutes=5),
        failed_attempts=40,
        failed_amount_minor=800_000,
    )

    return PaymentWindowSeries(
        baseline_windows=baseline_windows,
        current_window=current_window,
    )


@pytest.mark.asyncio
async def test_runs_complete_payment_method_detection_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=AsyncSession)
    series = create_series()

    persistence_result = MagicMock(
        spec=IncidentPersistenceResult,
    )

    load_windows = AsyncMock(
        return_value=series,
    )
    persist_detection = AsyncMock(
        return_value=persistence_result,
    )

    monkeypatch.setattr(
        incident_detection_runner,
        "load_payment_method_window_series",
        load_windows,
    )
    monkeypatch.setattr(
        incident_detection_runner,
        "persist_incident_detection",
        persist_detection,
    )

    result = await run_payment_method_incident_detection(
        session,
        payment_method="  UPI  ",
        currency="inr",
        reference_time=REFERENCE_TIME,
        baseline_window_count=6,
    )

    assert result.payment_method == "upi"
    assert result.currency == "INR"
    assert result.current_window_end == CURRENT_WINDOW_END
    assert result.decision.outcome is (IncidentDetectionOutcome.INCIDENT)
    assert result.persistence is persistence_result

    load_windows.assert_awaited_once_with(
        session,
        payment_method="upi",
        currency="INR",
        current_window_end=CURRENT_WINDOW_END,
        window_size=timedelta(minutes=5),
        baseline_window_count=6,
    )

    persist_detection.assert_awaited_once_with(
        session,
        detector_run_id=result.detector_run_id,
        metrics=result.metrics,
        baseline=result.baseline,
        decision=result.decision,
        currency="INR",
        detected_at=REFERENCE_TIME,
    )


@pytest.mark.asyncio
async def test_preserves_supplied_run_and_detection_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=AsyncSession)
    series = create_series()

    persistence_result = MagicMock(
        spec=IncidentPersistenceResult,
    )
    load_windows = AsyncMock(
        return_value=series,
    )
    persist_detection = AsyncMock(
        return_value=persistence_result,
    )

    monkeypatch.setattr(
        incident_detection_runner,
        "load_payment_method_window_series",
        load_windows,
    )
    monkeypatch.setattr(
        incident_detection_runner,
        "persist_incident_detection",
        persist_detection,
    )

    detector_run_id = uuid4()
    detected_at = REFERENCE_TIME + timedelta(seconds=30)

    result = await run_payment_method_incident_detection(
        session,
        payment_method="upi",
        currency="INR",
        reference_time=REFERENCE_TIME,
        detector_run_id=detector_run_id,
        detected_at=detected_at,
        baseline_window_count=6,
    )

    assert result.detector_run_id == detector_run_id

    persist_detection.assert_awaited_once_with(
        session,
        detector_run_id=detector_run_id,
        metrics=result.metrics,
        baseline=result.baseline,
        decision=result.decision,
        currency="INR",
        detected_at=detected_at,
    )
