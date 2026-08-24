from datetime import UTC, datetime, timedelta

import pytest

from app.domain.incidents import IncidentScope
from app.services.incident_window_aggregator import (
    PaymentOutcomeSample,
    build_payment_window_series,
    resolve_latest_closed_window_end,
)

WINDOW_END = datetime(
    2026,
    8,
    24,
    10,
    0,
    tzinfo=UTC,
)


def create_sample(
    occurred_at: datetime,
    *,
    amount_minor: int = 10_000,
    failed: bool = False,
) -> PaymentOutcomeSample:
    return PaymentOutcomeSample(
        occurred_at=occurred_at,
        amount_minor=amount_minor,
        failed=failed,
    )


def test_resolves_latest_closed_five_minute_window() -> None:
    reference_time = datetime(
        2026,
        8,
        24,
        10,
        7,
        59,
        tzinfo=UTC,
    )

    result = resolve_latest_closed_window_end(
        reference_time,
    )

    assert result == datetime(
        2026,
        8,
        24,
        10,
        5,
        tzinfo=UTC,
    )


def test_rejects_naive_reference_time() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        resolve_latest_closed_window_end(
            datetime(2026, 8, 24, 10, 7),
        )


def test_builds_baseline_and_current_window() -> None:
    samples = [
        create_sample(
            WINDOW_END - timedelta(minutes=14),
            amount_minor=10_000,
        ),
        create_sample(
            WINDOW_END - timedelta(minutes=9),
            amount_minor=20_000,
            failed=True,
        ),
        create_sample(
            WINDOW_END - timedelta(minutes=4),
            amount_minor=30_000,
            failed=True,
        ),
        create_sample(
            WINDOW_END - timedelta(minutes=3),
            amount_minor=40_000,
        ),
    ]

    series = build_payment_window_series(
        samples,
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value="upi",
        current_window_end=WINDOW_END,
        baseline_window_count=2,
    )

    assert len(series.baseline_windows) == 2

    first_baseline = series.baseline_windows[0]
    second_baseline = series.baseline_windows[1]
    current = series.current_window

    assert first_baseline.total_attempts == 1
    assert first_baseline.failed_attempts == 0
    assert first_baseline.total_amount_minor == 10_000

    assert second_baseline.total_attempts == 1
    assert second_baseline.failed_attempts == 1
    assert second_baseline.failed_amount_minor == 20_000

    assert current.total_attempts == 2
    assert current.failed_attempts == 1
    assert current.total_amount_minor == 70_000
    assert current.failed_amount_minor == 30_000


def test_zero_fills_windows_without_payments() -> None:
    series = build_payment_window_series(
        [],
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value="card",
        current_window_end=WINDOW_END,
        baseline_window_count=3,
    )

    assert len(series.baseline_windows) == 3
    assert all(window.total_attempts == 0 for window in series.baseline_windows)
    assert series.current_window.total_attempts == 0


def test_uses_half_open_window_boundaries() -> None:
    series_start = WINDOW_END - timedelta(minutes=15)

    samples = [
        create_sample(series_start),
        create_sample(WINDOW_END),
    ]

    series = build_payment_window_series(
        samples,
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value="upi",
        current_window_end=WINDOW_END,
        baseline_window_count=2,
    )

    assert series.baseline_windows[0].total_attempts == 1
    assert series.current_window.total_attempts == 0


def test_ignores_samples_before_requested_history() -> None:
    samples = [
        create_sample(
            WINDOW_END - timedelta(minutes=16),
            failed=True,
        ),
    ]

    series = build_payment_window_series(
        samples,
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value="upi",
        current_window_end=WINDOW_END,
        baseline_window_count=2,
    )

    assert all(window.total_attempts == 0 for window in series.baseline_windows)
    assert series.current_window.total_attempts == 0


def test_rejects_naive_sample_timestamp() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        create_sample(
            datetime(2026, 8, 24, 10, 0),
        )


def test_rejects_negative_sample_amount() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        create_sample(
            WINDOW_END,
            amount_minor=-1,
        )
