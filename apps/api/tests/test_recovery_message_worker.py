import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.recovery_message_batch import (
    RecoveryMessageBatchFailure,
    RecoveryMessageBatchResult,
)
from app.workers import recovery_message_worker


def build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        recovery_action_batch_size=25,
        recovery_action_claim_timeout_seconds=120,
        recovery_action_max_attempts=3,
        recovery_action_poll_interval_seconds=2.0,
    )


def build_result(
    *,
    discovered: int = 0,
) -> RecoveryMessageBatchResult:
    return RecoveryMessageBatchResult(
        discovered=discovered,
        succeeded=1 if discovered else 0,
        already_succeeded=0,
        policy_denied=0,
        retryable_failures=0,
        permanent_failures=0,
        skipped=0,
    )


def test_parse_run_once_defaults_to_continuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["recovery_message_worker"],
    )

    assert recovery_message_worker.parse_run_once() is False


def test_parse_run_once_accepts_once_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recovery_message_worker",
            "--once",
        ],
    )

    assert recovery_message_worker.parse_run_once() is True


@pytest.mark.asyncio
async def test_run_once_processes_one_batch_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings()
    session_factory = MagicMock()
    customer_provider = MagicMock()
    notification_provider = MagicMock()
    result = build_result(discovered=1)

    get_settings = MagicMock(
        return_value=settings,
    )
    get_session_factory = MagicMock(
        return_value=session_factory,
    )
    create_customer_provider = MagicMock(
        return_value=customer_provider,
    )
    create_notification_provider = MagicMock(
        return_value=notification_provider,
    )
    run_batch = AsyncMock(
        return_value=result,
    )
    close_database = AsyncMock()

    monkeypatch.setattr(
        recovery_message_worker,
        "get_settings",
        get_settings,
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "get_session_factory",
        get_session_factory,
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_customer_provider",
        create_customer_provider,
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_link_notification_provider",
        create_notification_provider,
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "run_recovery_message_batch",
        run_batch,
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "close_database",
        close_database,
    )

    await recovery_message_worker.run_recovery_message_worker(
        run_once=True,
    )

    create_customer_provider.assert_called_once_with(settings)
    create_notification_provider.assert_called_once_with(settings)

    run_batch.assert_awaited_once()

    batch_call = run_batch.await_args

    assert batch_call.args[0] is session_factory
    assert batch_call.kwargs["customer_provider"] is customer_provider
    assert batch_call.kwargs["notification_provider"] is notification_provider
    assert batch_call.kwargs["batch_size"] == 25
    assert batch_call.kwargs["claim_timeout"] == timedelta(
        seconds=120,
    )
    assert batch_call.kwargs["maximum_attempts"] == 3

    close_database.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_rejects_missing_customer_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_worker,
        "get_settings",
        MagicMock(
            return_value=build_settings(),
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_customer_provider",
        MagicMock(
            return_value=None,
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_link_notification_provider",
        MagicMock(
            return_value=MagicMock(),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Razorpay Key ID and Key Secret",
    ):
        await recovery_message_worker.run_recovery_message_worker(
            run_once=True,
        )


@pytest.mark.asyncio
async def test_run_once_rejects_missing_notification_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_worker,
        "get_settings",
        MagicMock(
            return_value=build_settings(),
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_customer_provider",
        MagicMock(
            return_value=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_link_notification_provider",
        MagicMock(
            return_value=None,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Razorpay Key ID and Key Secret",
    ):
        await recovery_message_worker.run_recovery_message_worker(
            run_once=True,
        )


@pytest.mark.asyncio
async def test_run_once_closes_resources_when_batch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_worker,
        "get_settings",
        MagicMock(
            return_value=build_settings(),
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_customer_provider",
        MagicMock(
            return_value=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "create_razorpay_payment_link_notification_provider",
        MagicMock(
            return_value=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "get_session_factory",
        MagicMock(
            return_value=MagicMock(),
        ),
    )

    run_batch = AsyncMock(
        side_effect=RuntimeError(
            "Database temporarily unavailable",
        ),
    )
    close_database = AsyncMock()

    monkeypatch.setattr(
        recovery_message_worker,
        "run_recovery_message_batch",
        run_batch,
    )
    monkeypatch.setattr(
        recovery_message_worker,
        "close_database",
        close_database,
    )

    with pytest.raises(
        RuntimeError,
        match="Database temporarily unavailable",
    ):
        await recovery_message_worker.run_recovery_message_worker(
            run_once=True,
        )

    run_batch.assert_awaited_once()
    close_database.assert_awaited_once()


def test_log_batch_result_logs_each_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = RecoveryMessageBatchResult(
        discovered=1,
        succeeded=0,
        already_succeeded=0,
        policy_denied=0,
        retryable_failures=1,
        permanent_failures=0,
        skipped=0,
        failures=(
            RecoveryMessageBatchFailure(
                action_id=UUID(
                    "10000000-0000-0000-0000-000000000001",
                ),
                error_type="RecoveryMessageProviderFailure",
                retryable=True,
            ),
        ),
    )

    with caplog.at_level(
        "INFO",
        logger="reclaimrail.recovery-message-worker",
    ):
        recovery_message_worker.log_batch_result(result)

    assert "discovered=1" in caplog.text
    assert "retryable=True" in caplog.text
