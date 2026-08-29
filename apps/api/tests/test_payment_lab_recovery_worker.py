import asyncio
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.recovery import RecoveryPlannerPolicy
from app.services.payment_lab_recovery_batch import PaymentLabRecoveryBatchResult
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
        recovery_approval_threshold_minor=300_000,
        recovery_approval_ttl_seconds=900,
        recovery_incident_recheck_delay_seconds=900,
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
        provider=provider,
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
