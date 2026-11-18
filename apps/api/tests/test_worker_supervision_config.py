import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_worker_supervision_defaults_are_safe() -> None:
    settings = Settings()

    assert settings.worker_heartbeat_interval_seconds == 5
    assert settings.worker_delayed_after_seconds == 15
    assert settings.worker_heartbeat_ttl_seconds == 30
    assert settings.payment_truth_reconciliation_retry_base_seconds == 15
    assert settings.payment_truth_reconciliation_retry_max_seconds == 300
    assert settings.payment_truth_reconciliation_max_attempts == 5
    assert settings.payment_truth_reconciliation_circuit_failure_threshold == 3
    assert settings.payment_truth_reconciliation_circuit_open_seconds == 300


def test_worker_heartbeat_ttl_must_exceed_two_intervals() -> None:
    with pytest.raises(ValidationError, match="heartbeat TTL"):
        Settings(
            worker_heartbeat_interval_seconds=10,
            worker_heartbeat_ttl_seconds=20,
        )


def test_worker_delayed_threshold_must_precede_expiry() -> None:
    with pytest.raises(ValidationError, match="delayed threshold"):
        Settings(
            worker_delayed_after_seconds=30,
            worker_heartbeat_ttl_seconds=30,
        )


def test_reconciliation_retry_maximum_must_not_be_lower_than_base() -> None:
    with pytest.raises(ValidationError, match="reconciliation retry maximum"):
        Settings(
            payment_truth_reconciliation_retry_base_seconds=60,
            payment_truth_reconciliation_retry_max_seconds=30,
        )


def test_reconciliation_circuit_threshold_must_fit_retry_budget() -> None:
    with pytest.raises(ValidationError, match="circuit threshold"):
        Settings(
            payment_truth_reconciliation_circuit_failure_threshold=6,
            payment_truth_reconciliation_max_attempts=5,
        )
