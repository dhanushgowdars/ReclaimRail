from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.integrations.razorpay.payment_customers import (
    RazorpayPaymentCustomerProviderError,
)
from app.integrations.razorpay.payment_link_notifications import (
    RazorpayPaymentLinkNotificationError,
    RazorpayPaymentLinkNotificationMedium,
)
from app.services import recovery_message_executor
from app.services.recovery_action_executor import (
    RecoveryActionExecutionDisposition,
    RecoveryActionExecutionResult,
    RecoveryActionNotExecutableError,
)
from app.services.recovery_message_executor import (
    PreparedRecoveryMessageAction,
    RecoveryMessageActionPreparation,
    RecoveryMessageProviderError,
    RecoveryMessageProviderFailure,
    _has_contact_for_medium,
    _notification_medium,
    execute_recovery_message_action,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

ACTION_ID = UUID("10000000-0000-0000-0000-000000000001")
CASE_ID = UUID("20000000-0000-0000-0000-000000000001")


def build_prepared_action(
    *,
    medium: RazorpayPaymentLinkNotificationMedium = (RazorpayPaymentLinkNotificationMedium.EMAIL),
) -> PreparedRecoveryMessageAction:
    return PreparedRecoveryMessageAction(
        action_id=ACTION_ID,
        recovery_case_id=CASE_ID,
        provider_payment_id="pay_rr_message_001",
        payment_link_id="plink_rr_message_001",
        medium=medium,
        attempt_number=1,
    )


def build_result(
    disposition: RecoveryActionExecutionDisposition,
) -> RecoveryActionExecutionResult:
    return RecoveryActionExecutionResult(
        action_id=ACTION_ID,
        recovery_case_id=CASE_ID,
        disposition=disposition,
    )


def build_session_factory() -> MagicMock:
    session_factory = MagicMock()

    contexts: list[MagicMock] = []

    for _ in range(3):
        context = MagicMock()
        context.__aenter__ = AsyncMock(
            return_value=MagicMock(),
        )
        context.__aexit__ = AsyncMock(
            return_value=False,
        )
        contexts.append(context)

    session_factory.begin.side_effect = contexts

    return session_factory


def build_customer_provider(
    *,
    email: str | None = "customer@example.com",
    contact: str | None = "+919876543210",
) -> MagicMock:
    provider = MagicMock()
    provider.fetch_payment_customer = AsyncMock(
        return_value=SimpleNamespace(
            email=email,
            contact=contact,
        ),
    )
    return provider


def build_notification_provider() -> MagicMock:
    provider = MagicMock()
    provider.send_notification = AsyncMock()
    return provider


def build_direct_email_provider() -> MagicMock:
    provider = MagicMock()
    provider.send_recovery_email = AsyncMock(
        return_value=SimpleNamespace(id="email_rr_001"),
    )
    return provider


def test_notification_medium_accepts_email_and_sms() -> None:
    assert _notification_medium("email") is RazorpayPaymentLinkNotificationMedium.EMAIL
    assert _notification_medium("sms") is RazorpayPaymentLinkNotificationMedium.SMS


def test_notification_medium_rejects_unsupported_channel() -> None:
    with pytest.raises(
        RecoveryActionNotExecutableError,
        match="supported email or SMS channel",
    ):
        _notification_medium("whatsapp")


@pytest.mark.parametrize(
    ("medium", "email", "contact", "expected"),
    [
        (
            RazorpayPaymentLinkNotificationMedium.EMAIL,
            "customer@example.com",
            None,
            True,
        ),
        (
            RazorpayPaymentLinkNotificationMedium.EMAIL,
            None,
            "+919876543210",
            False,
        ),
        (
            RazorpayPaymentLinkNotificationMedium.SMS,
            None,
            "+919876543210",
            True,
        ),
        (
            RazorpayPaymentLinkNotificationMedium.SMS,
            "customer@example.com",
            None,
            False,
        ),
    ],
)
def test_contact_must_match_selected_channel(
    *,
    medium: RazorpayPaymentLinkNotificationMedium,
    email: str | None,
    contact: str | None,
    expected: bool,
) -> None:
    assert (
        _has_contact_for_medium(
            medium=medium,
            email=email,
            contact=contact,
        )
        is expected
    )


def test_preparation_requires_exactly_one_result() -> None:
    prepared = build_prepared_action()
    terminal_result = build_result(
        RecoveryActionExecutionDisposition.SUCCEEDED,
    )

    with pytest.raises(
        ValueError,
        match="exactly one result",
    ):
        RecoveryMessageActionPreparation()

    with pytest.raises(
        ValueError,
        match="exactly one result",
    ):
        RecoveryMessageActionPreparation(
            prepared=prepared,
            terminal_result=terminal_result,
        )


@pytest.mark.asyncio
async def test_successfully_sends_email_without_persisting_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = build_prepared_action()
    completed_result = build_result(
        RecoveryActionExecutionDisposition.SUCCEEDED,
    )

    prepare = AsyncMock(
        return_value=RecoveryMessageActionPreparation(
            prepared=prepared,
        ),
    )
    complete = AsyncMock(
        return_value=completed_result,
    )

    monkeypatch.setattr(
        recovery_message_executor,
        "prepare_recovery_message_action",
        prepare,
    )
    monkeypatch.setattr(
        recovery_message_executor,
        "complete_recovery_message_action",
        complete,
    )

    session_factory = build_session_factory()
    customer_provider = build_customer_provider(
        email="customer@example.com",
        contact="+919876543210",
    )
    notification_provider = build_notification_provider()

    result = await execute_recovery_message_action(
        session_factory,
        action_id=ACTION_ID,
        customer_provider=customer_provider,
        notification_provider=notification_provider,
        executed_at=NOW,
    )

    assert result is completed_result

    customer_provider.fetch_payment_customer.assert_awaited_once_with(
        "pay_rr_message_001",
    )
    notification_provider.send_notification.assert_awaited_once_with(
        payment_link_id="plink_rr_message_001",
        medium=RazorpayPaymentLinkNotificationMedium.EMAIL,
    )

    complete.assert_awaited_once()
    completed_prepared = complete.await_args.kwargs["prepared"]

    assert completed_prepared is prepared
    assert not hasattr(completed_prepared, "email")
    assert not hasattr(completed_prepared, "contact")


@pytest.mark.asyncio
async def test_uses_direct_email_only_for_consent_recorded_demo_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedRecoveryMessageAction(
        action_id=ACTION_ID,
        recovery_case_id=CASE_ID,
        provider_payment_id="pay_rr_message_001",
        payment_link_id="plink_rr_message_001",
        medium=RazorpayPaymentLinkNotificationMedium.EMAIL,
        attempt_number=1,
        direct_email_eligible=True,
        payment_link_url="https://rzp.io/i/test",
        amount_minor=349_900,
        currency="INR",
    )
    completed_result = build_result(RecoveryActionExecutionDisposition.SUCCEEDED)
    prepare = AsyncMock(
        return_value=RecoveryMessageActionPreparation(prepared=prepared),
    )
    complete = AsyncMock(return_value=completed_result)
    monkeypatch.setattr(recovery_message_executor, "prepare_recovery_message_action", prepare)
    monkeypatch.setattr(recovery_message_executor, "complete_recovery_message_action", complete)

    customer_provider = build_customer_provider()
    notification_provider = build_notification_provider()
    direct_email_provider = build_direct_email_provider()

    result = await execute_recovery_message_action(
        build_session_factory(),
        action_id=ACTION_ID,
        customer_provider=customer_provider,
        notification_provider=notification_provider,
        direct_email_provider=direct_email_provider,
        direct_email_recipient="demo@example.com",
        executed_at=NOW,
    )

    assert result is completed_result
    direct_email_provider.send_recovery_email.assert_awaited_once_with(
        recipient="demo@example.com",
        payment_link_url="https://rzp.io/i/test",
        amount_minor=349_900,
        currency="INR",
    )
    customer_provider.fetch_payment_customer.assert_not_awaited()
    notification_provider.send_notification.assert_not_awaited()
    assert complete.await_args.kwargs["provider_action_id"] == "email_rr_001"
    assert complete.await_args.kwargs["provider_action_status"] == "direct_email_accepted"


@pytest.mark.asyncio
async def test_policy_terminal_result_does_not_fetch_or_notify_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_result = build_result(
        RecoveryActionExecutionDisposition.POLICY_STOPPED,
    )

    prepare = AsyncMock(
        return_value=RecoveryMessageActionPreparation(
            terminal_result=terminal_result,
        ),
    )

    monkeypatch.setattr(
        recovery_message_executor,
        "prepare_recovery_message_action",
        prepare,
    )

    session_factory = build_session_factory()
    customer_provider = build_customer_provider()
    notification_provider = build_notification_provider()

    result = await execute_recovery_message_action(
        session_factory,
        action_id=ACTION_ID,
        customer_provider=customer_provider,
        notification_provider=notification_provider,
        executed_at=NOW,
    )

    assert result is terminal_result
    customer_provider.fetch_payment_customer.assert_not_awaited()
    notification_provider.send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_succeeded_action_does_not_send_duplicate_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_result = build_result(
        RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED,
    )

    monkeypatch.setattr(
        recovery_message_executor,
        "prepare_recovery_message_action",
        AsyncMock(
            return_value=RecoveryMessageActionPreparation(
                terminal_result=terminal_result,
            ),
        ),
    )

    customer_provider = build_customer_provider()
    notification_provider = build_notification_provider()

    result = await execute_recovery_message_action(
        build_session_factory(),
        action_id=ACTION_ID,
        customer_provider=customer_provider,
        notification_provider=notification_provider,
        executed_at=NOW,
    )

    assert result is terminal_result
    customer_provider.fetch_payment_customer.assert_not_awaited()
    notification_provider.send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_selected_channel_contact_is_not_sent_and_is_escalated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = build_prepared_action()

    monkeypatch.setattr(
        recovery_message_executor,
        "prepare_recovery_message_action",
        AsyncMock(
            return_value=RecoveryMessageActionPreparation(
                prepared=prepared,
            ),
        ),
    )

    fail = AsyncMock(
        return_value=False,
    )
    monkeypatch.setattr(
        recovery_message_executor,
        "fail_recovery_message_action",
        fail,
    )

    customer_provider = build_customer_provider(
        email=None,
        contact="+919876543210",
    )
    notification_provider = build_notification_provider()

    with pytest.raises(
        RecoveryMessageProviderFailure,
    ) as raised:
        await execute_recovery_message_action(
            build_session_factory(),
            action_id=ACTION_ID,
            customer_provider=customer_provider,
            notification_provider=notification_provider,
            executed_at=NOW,
        )

    assert raised.value.retryable is False
    notification_provider.send_notification.assert_not_awaited()

    failure_error = fail.await_args.kwargs["error"]
    assert isinstance(
        failure_error,
        RecoveryMessageProviderError,
    )
    assert failure_error.delivery_attempted is False
    assert failure_error.retryable is False


@pytest.mark.asyncio
async def test_customer_lookup_failure_can_retry_before_delivery_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = build_prepared_action()

    monkeypatch.setattr(
        recovery_message_executor,
        "prepare_recovery_message_action",
        AsyncMock(
            return_value=RecoveryMessageActionPreparation(
                prepared=prepared,
            ),
        ),
    )

    fail = AsyncMock(
        return_value=True,
    )
    monkeypatch.setattr(
        recovery_message_executor,
        "fail_recovery_message_action",
        fail,
    )

    customer_provider = build_customer_provider()
    customer_provider.fetch_payment_customer.side_effect = RazorpayPaymentCustomerProviderError(
        "Razorpay customer lookup unavailable",
        retryable=True,
        status_code=503,
    )
    notification_provider = build_notification_provider()

    with pytest.raises(
        RecoveryMessageProviderFailure,
    ) as raised:
        await execute_recovery_message_action(
            build_session_factory(),
            action_id=ACTION_ID,
            customer_provider=customer_provider,
            notification_provider=notification_provider,
            executed_at=NOW,
        )

    assert raised.value.retryable is True
    assert raised.value.status_code == 503
    notification_provider.send_notification.assert_not_awaited()

    failure_error = fail.await_args.kwargs["error"]
    assert failure_error.delivery_attempted is False
    assert failure_error.retryable is True
    assert failure_error.status_code == 503


@pytest.mark.asyncio
async def test_notification_provider_failure_is_never_retried_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = build_prepared_action(
        medium=RazorpayPaymentLinkNotificationMedium.SMS,
    )

    monkeypatch.setattr(
        recovery_message_executor,
        "prepare_recovery_message_action",
        AsyncMock(
            return_value=RecoveryMessageActionPreparation(
                prepared=prepared,
            ),
        ),
    )

    fail = AsyncMock(
        return_value=False,
    )
    monkeypatch.setattr(
        recovery_message_executor,
        "fail_recovery_message_action",
        fail,
    )

    customer_provider = build_customer_provider(
        email=None,
        contact="+919876543210",
    )
    notification_provider = build_notification_provider()
    notification_provider.send_notification.side_effect = RazorpayPaymentLinkNotificationError(
        "Razorpay notification request timed out",
        retryable=True,
        status_code=503,
    )

    with pytest.raises(
        RecoveryMessageProviderFailure,
    ) as raised:
        await execute_recovery_message_action(
            build_session_factory(),
            action_id=ACTION_ID,
            customer_provider=customer_provider,
            notification_provider=notification_provider,
            executed_at=NOW,
        )

    assert raised.value.retryable is False
    assert raised.value.status_code == 503

    failure_error = fail.await_args.kwargs["error"]

    assert failure_error.delivery_attempted is True
    assert failure_error.retryable is False
    assert failure_error.status_code == 503
