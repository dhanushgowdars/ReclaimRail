import asyncio
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.recovery import RecoveryPlannerPolicy
from app.services.payment_lab_provider_verification import ProviderVerificationResult
from app.services.payment_lab_recovery_batch import PaymentLabRecoveryBatchResult
from app.services.payment_truth_reconciliation import PaymentTruthReconciliationResult
from app.workers import payment_lab_recovery_worker
from app.workers.payment_lab_recovery_worker import (
    parse_run_once,
    run_payment_lab_recovery_worker,
)

NOW = datetime(2026, 8, 26, 18, 30, tzinfo=UTC)


def create_settings() -> SimpleNamespace:
    return SimpleNamespace(
        payment_lab_recovery_batch_size=25,
        payment_lab_recovery_poll_interval_seconds=1.0,
        payment_lab_recovery_claim_timeout_seconds=60,
        payment_truth_reconciliation_retry_base_seconds=15.0,
        payment_truth_reconciliation_retry_max_seconds=300.0,
        payment_truth_reconciliation_max_attempts=5,
        payment_truth_reconciliation_circuit_failure_threshold=3,
        payment_truth_reconciliation_circuit_open_seconds=300.0,
        recovery_approval_threshold_minor=300_000,
        recovery_approval_ttl_seconds=900,
        recovery_incident_recheck_delay_seconds=900,
        recovery_investigator_shadow_enabled=True,
        recovery_investigator_max_tool_calls=8,
        recovery_investigator_max_model_retries=2,
        recovery_investigator_retry_base_seconds=0.5,
        recovery_investigator_retry_max_seconds=4.0,
        recovery_investigator_retry_jitter_ratio=0.2,
        recovery_investigator_max_total_tokens=12_000,
        recovery_investigator_max_duration_seconds=30,
    )


def stub_order_provider(monkeypatch: pytest.MonkeyPatch, provider: object | None = None) -> None:
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_razorpay_order_provider",
        MagicMock(return_value=provider),
    )


def create_batch_result() -> PaymentLabRecoveryBatchResult:
    return PaymentLabRecoveryBatchResult(
        discovered_run_ids=(),
        start_results=(),
        failures=(),
        skipped_run_ids=(),
    )


def test_parse_run_once_defaults_to_continuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["payment_lab_recovery_worker"])
    assert parse_run_once() is False


def test_parse_run_once_accepts_once_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["payment_lab_recovery_worker", "--once"],
    )
    assert parse_run_once() is True


@pytest.mark.asyncio
async def test_run_once_executes_batch_and_closes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = create_settings()
    provider = MagicMock(name="gemini_provider")
    investigator_provider = MagicMock(name="investigator_provider")
    session_factory = MagicMock(name="session_factory")
    run_batch = AsyncMock(return_value=create_batch_result())
    close_database = AsyncMock()

    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_settings",
        MagicMock(return_value=settings),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_gemini_recovery_plan_provider",
        MagicMock(return_value=provider),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_groq_evidence_investigator",
        MagicMock(return_value=investigator_provider),
    )
    stub_order_provider(monkeypatch)
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_session_factory",
        MagicMock(return_value=session_factory),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "run_payment_lab_recovery_batch",
        run_batch,
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "close_database",
        close_database,
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "utc_now",
        MagicMock(return_value=NOW),
    )

    await run_payment_lab_recovery_worker(run_once=True)

    run_batch.assert_awaited_once_with(
        session_factory,
        reference_time=NOW,
        provider=None,
        investigator_provider=investigator_provider,
        investigator_budgets=payment_lab_recovery_worker.InvestigationBudgets(),
        batch_size=25,
        claim_timeout=timedelta(seconds=60),
        approval_threshold_minor=300_000,
        approval_window=timedelta(seconds=900),
        planner_policy=RecoveryPlannerPolicy(
            incident_recheck_delay=timedelta(seconds=900),
        ),
    )
    close_database.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_reconciliation_settings_and_persisted_control_counts_reach_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = create_settings()
    order_provider = MagicMock(name="order_provider")
    session_factory = MagicMock(name="session_factory")
    reconciliation = AsyncMock(
        return_value=PaymentTruthReconciliationResult(
            checked=1,
            projected=0,
            unchanged=0,
            unavailable=1,
            persistence_failures=0,
            circuit_opened=True,
            provider_calls=1,
            cooling_down_controls=1,
            open_circuit_controls=1,
            exhausted_controls=2,
            synthetic_blocked_controls=1,
        ),
    )
    heartbeat = MagicMock()
    heartbeat.start = AsyncMock()
    heartbeat.stop = AsyncMock()
    heartbeat.record_success = AsyncMock()
    heartbeat.record_failure = AsyncMock()

    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_settings",
        MagicMock(return_value=settings),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_gemini_recovery_plan_provider",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_groq_evidence_investigator",
        MagicMock(return_value=None),
    )
    stub_order_provider(monkeypatch, order_provider)
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_session_factory",
        MagicMock(return_value=session_factory),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_worker_heartbeat_reporter",
        MagicMock(return_value=heartbeat),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "reconcile_payment_truth_batch",
        reconciliation,
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "verify_payment_lab_provider_evidence_batch",
        AsyncMock(
            return_value=ProviderVerificationResult(
                checked=0,
                projected=0,
                no_payment_yet=0,
                failures=0,
            ),
        ),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "run_payment_lab_recovery_batch",
        AsyncMock(return_value=create_batch_result()),
    )
    monkeypatch.setattr(payment_lab_recovery_worker, "utc_now", MagicMock(return_value=NOW))
    monkeypatch.setattr(payment_lab_recovery_worker, "close_database", AsyncMock())
    monkeypatch.setattr(payment_lab_recovery_worker, "close_redis", AsyncMock())

    await run_payment_lab_recovery_worker(run_once=True)

    reconciliation.assert_awaited_once_with(
        session_factory,
        provider=order_provider,
        reference_time=NOW,
        batch_size=25,
        retry_base_delay=timedelta(seconds=15),
        retry_maximum_delay=timedelta(seconds=300),
        max_attempts=5,
        circuit_failure_threshold=3,
        circuit_open_duration=timedelta(seconds=300),
    )
    metrics = heartbeat.record_success.await_args.args[0]
    assert metrics["truth_reconciliation_provider_calls"] == 1
    assert metrics["truth_reconciliation_cooling_controls"] == 1
    assert metrics["truth_reconciliation_open_circuit_controls"] == 1
    assert metrics["truth_reconciliation_exhausted_controls"] == 2
    assert metrics["truth_reconciliation_synthetic_blocked_controls"] == 1


@pytest.mark.asyncio
async def test_run_once_closes_database_after_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_database = AsyncMock()
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_settings",
        MagicMock(return_value=create_settings()),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_gemini_recovery_plan_provider",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_groq_evidence_investigator",
        MagicMock(return_value=None),
    )
    stub_order_provider(monkeypatch)
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_session_factory",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "run_payment_lab_recovery_batch",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await run_payment_lab_recovery_worker(run_once=True)

    close_database.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_continuous_empty_batch_sleeps_and_closes_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_database = AsyncMock()
    sleep = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_settings",
        MagicMock(return_value=create_settings()),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_gemini_recovery_plan_provider",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "create_groq_evidence_investigator",
        MagicMock(return_value=None),
    )
    stub_order_provider(monkeypatch)
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "get_session_factory",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "run_payment_lab_recovery_batch",
        AsyncMock(return_value=create_batch_result()),
    )
    monkeypatch.setattr(
        payment_lab_recovery_worker,
        "close_database",
        close_database,
    )
    monkeypatch.setattr(payment_lab_recovery_worker.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await run_payment_lab_recovery_worker(run_once=False)

    sleep.assert_awaited_once_with(1.0)
    close_database.assert_awaited_once_with()
