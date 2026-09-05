import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
)
from app.services.recovery_outcome_batch import (
    RecoveryOutcomeBatchResult,
)
from app.workers import recovery_outcome_worker
from app.workers.recovery_outcome_worker import (
    parse_run_once,
    run_recovery_outcome_worker,
)

NOW = datetime(
    2026,
    8,
    25,
    19,
    30,
    tzinfo=UTC,
)


def create_settings() -> SimpleNamespace:
    return SimpleNamespace(
        recovery_outcome_batch_size=25,
        recovery_outcome_poll_interval_seconds=30.0,
    )


def create_batch_result(
    *,
    discovered_action_ids: tuple[UUID, ...] = (),
) -> RecoveryOutcomeBatchResult:
    return RecoveryOutcomeBatchResult(
        discovered_action_ids=discovered_action_ids,
        reconciliation_results=(),
        failures=(),
        skipped_action_ids=(),
    )


def test_parse_run_once_defaults_to_continuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["recovery_outcome_worker"],
    )

    assert parse_run_once() is False


def test_parse_run_once_accepts_once_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recovery_outcome_worker",
            "--once",
        ],
    )

    assert parse_run_once() is True


@pytest.mark.asyncio
async def test_run_once_executes_batch_and_closes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = create_settings()
    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )
    session_factory = MagicMock(
        name="session_factory",
    )
    run_batch = AsyncMock(
        return_value=create_batch_result(),
    )
    close_database = AsyncMock()

    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_settings",
        MagicMock(
            return_value=settings,
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "create_razorpay_payment_link_provider",
        MagicMock(
            return_value=provider,
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_session_factory",
        MagicMock(
            return_value=session_factory,
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "run_recovery_outcome_batch",
        run_batch,
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "close_database",
        close_database,
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "utc_now",
        MagicMock(
            return_value=NOW,
        ),
    )

    await run_recovery_outcome_worker(
        run_once=True,
    )

    run_batch.assert_awaited_once_with(
        session_factory,
        provider=provider,
        reference_time=NOW,
        batch_size=1,
    )
    close_database.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_run_once_closes_database_after_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )
    close_database = AsyncMock()

    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_settings",
        MagicMock(
            return_value=create_settings(),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "create_razorpay_payment_link_provider",
        MagicMock(
            return_value=provider,
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_session_factory",
        MagicMock(
            return_value=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "run_recovery_outcome_batch",
        AsyncMock(
            side_effect=RuntimeError(
                "database unavailable",
            ),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "close_database",
        close_database,
    )

    with pytest.raises(
        RuntimeError,
        match="database unavailable",
    ):
        await run_recovery_outcome_worker(
            run_once=True,
        )

    close_database.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_database_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_session_factory = MagicMock()
    close_database = AsyncMock()

    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_settings",
        MagicMock(
            return_value=create_settings(),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "create_razorpay_payment_link_provider",
        MagicMock(
            return_value=None,
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_session_factory",
        get_session_factory,
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "close_database",
        close_database,
    )

    with pytest.raises(
        RuntimeError,
        match="Key ID and Key Secret",
    ):
        await run_recovery_outcome_worker(
            run_once=True,
        )

    get_session_factory.assert_not_called()
    close_database.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "discovered_action_ids",
    [
        (),
        (UUID("97000000-0000-0000-0000-000000000001"),),
    ],
)
async def test_continuous_batch_sleeps_and_closes_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    discovered_action_ids: tuple[UUID, ...],
) -> None:
    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )
    close_database = AsyncMock()
    sleep = AsyncMock(
        side_effect=asyncio.CancelledError(),
    )

    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_settings",
        MagicMock(
            return_value=create_settings(),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "create_razorpay_payment_link_provider",
        MagicMock(
            return_value=provider,
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "get_session_factory",
        MagicMock(
            return_value=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "run_recovery_outcome_batch",
        AsyncMock(
            return_value=create_batch_result(
                discovered_action_ids=discovered_action_ids,
            ),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_worker,
        "close_database",
        close_database,
    )
    monkeypatch.setattr(
        recovery_outcome_worker.asyncio,
        "sleep",
        sleep,
    )

    with pytest.raises(
        asyncio.CancelledError,
    ):
        await run_recovery_outcome_worker(
            run_once=False,
        )

    sleep.assert_awaited_once_with(
        120.0,
    )
    close_database.assert_awaited_once_with()
