from datetime import UTC, datetime, timedelta

import pytest

from app.domain.incidents import (
    IncidentDetectionOutcome,
    IncidentReason,
    IncidentScope,
    IncidentSeverity,
    PaymentWindowMetrics,
    build_baseline_profile,
    build_incident_fingerprint,
    detect_payment_degradation,
)

BASE_TIME = datetime(
    2026,
    8,
    24,
    10,
    0,
    tzinfo=UTC,
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


def create_baseline() -> list[PaymentWindowMetrics]:
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

    return [
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


def test_builds_robust_baseline_from_historical_windows() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )

    assert baseline.window_count == 8
    assert baseline.median_failure_rate == pytest.approx(
        0.05,
    )
    assert baseline.mad_failure_rate >= 0.0


def test_rejects_invalid_window_counts() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed",
    ):
        create_window(
            0,
            total_attempts=10,
            failed_attempts=11,
            failed_amount_minor=100_000,
        )


def test_reports_insufficient_data_for_small_window() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )
    metrics = create_window(
        20,
        total_attempts=10,
        failed_attempts=5,
        failed_amount_minor=100_000,
    )

    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    assert decision.outcome is (IncidentDetectionOutcome.INSUFFICIENT_DATA)
    assert decision.severity is None


def test_normal_window_does_not_open_incident() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )
    metrics = create_window(
        20,
        total_attempts=100,
        failed_attempts=7,
        failed_amount_minor=70_000,
    )

    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    assert decision.outcome is (IncidentDetectionOutcome.NORMAL)
    assert decision.severity is None


def test_detects_payment_method_degradation() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )
    metrics = create_window(
        20,
        total_attempts=100,
        failed_attempts=40,
        failed_amount_minor=800_000,
    )

    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    assert decision.outcome is (IncidentDetectionOutcome.INCIDENT)
    assert decision.severity is IncidentSeverity.HIGH
    assert decision.failure_rate == pytest.approx(0.40)
    assert decision.absolute_uplift == pytest.approx(
        0.35,
    )
    assert decision.revenue_at_risk_minor == 800_000
    assert decision.confidence > 0.5

    assert IncidentReason.ROBUST_DEVIATION in (decision.reason_codes)
    assert IncidentReason.RATE_MULTIPLIER in (decision.reason_codes)


def test_mad_floor_handles_zero_variance_baseline() -> None:
    historical_windows = [
        create_window(
            index,
            total_attempts=100,
            failed_attempts=5,
            failed_amount_minor=50_000,
        )
        for index in range(8)
    ]
    baseline = build_baseline_profile(
        historical_windows,
    )
    metrics = create_window(
        20,
        total_attempts=100,
        failed_attempts=30,
        failed_amount_minor=600_000,
    )

    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    assert baseline.mad_failure_rate == 0.0
    assert decision.outcome is (IncidentDetectionOutcome.INCIDENT)
    assert decision.robust_z_score > 3.5


def test_revenue_floor_suppresses_low_value_noise() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )
    metrics = create_window(
        20,
        total_attempts=100,
        failed_attempts=50,
        failed_amount_minor=10_000,
    )

    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    assert decision.outcome is (IncidentDetectionOutcome.NORMAL)


def test_high_value_loss_becomes_critical() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )
    metrics = create_window(
        20,
        total_attempts=100,
        failed_attempts=50,
        failed_amount_minor=3_000_000,
    )

    decision = detect_payment_degradation(
        metrics,
        baseline,
    )

    assert decision.outcome is (IncidentDetectionOutcome.INCIDENT)
    assert decision.severity is (IncidentSeverity.CRITICAL)


def test_fingerprint_is_stable_across_formatting() -> None:
    first = build_incident_fingerprint(
        IncidentScope.PAYMENT_METHOD,
        "  UPI  ",
    )
    second = build_incident_fingerprint(
        IncidentScope.PAYMENT_METHOD,
        "upi",
    )

    assert first == second
    assert first == ("payment_degradation:payment_method:upi")


def test_rejects_mismatched_baseline_dimension() -> None:
    baseline = build_baseline_profile(
        create_baseline(),
    )
    card_metrics = create_window(
        20,
        total_attempts=100,
        failed_attempts=40,
        failed_amount_minor=800_000,
        dimension_value="card",
    )

    with pytest.raises(
        ValueError,
        match="dimensions do not match",
    ):
        detect_payment_degradation(
            card_metrics,
            baseline,
        )
