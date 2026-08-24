from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import (
    PaymentAttempt,
    PaymentStateTransition,
)
from app.domain.payments import (
    PaymentLifecycleEvent,
    PaymentState,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
)
from app.services.payment_projector import (
    PaymentProjectionConflictError,
    project_payment_lifecycle_event,
)

ATTEMPT_ID = UUID("30000000-0000-0000-0000-000000000001")
WEBHOOK_ID = UUID("40000000-0000-0000-0000-000000000001")
EXISTING_WEBHOOK_ID = UUID("40000000-0000-0000-0000-000000000002")
TRANSITION_ID = UUID("50000000-0000-0000-0000-000000000001")

PAYMENT_CREATED_AT = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
EVENT_CREATED_AT = datetime(2026, 8, 24, 8, 2, tzinfo=UTC)
PROCESSED_AT = datetime(2026, 8, 24, 8, 3, tzinfo=UTC)


def make_event(
    *,
    state: PaymentState = PaymentState.FAILED,
    amount_minor: int = 50_000,
) -> PaymentLifecycleEvent:
    event_types = {
        PaymentState.FAILED: "payment.failed",
        PaymentState.AUTHORIZED: "payment.authorized",
        PaymentState.CAPTURED: "payment.captured",
        PaymentState.REFUNDED: "payment.refunded",
    }

    is_failure = state is PaymentState.FAILED

    return PaymentLifecycleEvent(
        webhook_event_id=WEBHOOK_ID,
        provider_event_id="evt_transaction_test",
        provider="razorpay",
        account_id="acc_transaction_test",
        event_type=event_types[state],
        payment_id="pay_transaction_test",
        order_id="order_transaction_test",
        state=state,
        amount_minor=amount_minor,
        currency="INR",
        method="upi",
        event_created_at=EVENT_CREATED_AT,
        payment_created_at=PAYMENT_CREATED_AT,
        error_code="BAD_REQUEST_ERROR" if is_failure else None,
        error_description="Payment declined" if is_failure else None,
        error_source="customer" if is_failure else None,
        error_step="payment_authentication" if is_failure else None,
        error_reason="payment_failed" if is_failure else None,
    )


def make_attempt(
    *,
    state: PaymentState = PaymentState.UNKNOWN,
    state_version: int = 0,
    amount_minor: int = 50_000,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=ATTEMPT_ID,
        provider="razorpay",
        provider_payment_id="pay_transaction_test",
        account_id="acc_transaction_test",
        provider_order_id="order_transaction_test",
        amount_minor=amount_minor,
        currency="INR",
        method="upi",
        payment_created_at=PAYMENT_CREATED_AT,
        current_state=state.value,
        state_version=state_version,
        state_provider_event_id="evt_existing",
        state_webhook_event_id=EXISTING_WEBHOOK_ID,
        state_event_created_at=EVENT_CREATED_AT,
        error_code=None,
        error_description=None,
        error_source=None,
        error_step=None,
        error_reason=None,
        recovery_eligible=state is PaymentState.FAILED,
        recovery_stopped_at=None,
        recovery_stop_reason=None,
        late_authorization_detected_at=None,
        created_at=PAYMENT_CREATED_AT,
        updated_at=PAYMENT_CREATED_AT,
    )


def make_existing_transition() -> PaymentStateTransition:
    return PaymentStateTransition(
        id=TRANSITION_ID,
        payment_attempt_id=ATTEMPT_ID,
        webhook_event_id=WEBHOOK_ID,
        provider_event_id="evt_transaction_test",
        event_type="payment.failed",
        previous_state=PaymentState.UNKNOWN.value,
        incoming_state=PaymentState.FAILED.value,
        resulting_state=PaymentState.FAILED.value,
        resulting_version=1,
        outcome=PaymentTransitionOutcome.APPLIED.value,
        reason=PaymentTransitionReason.INITIALIZED.value,
        late_authorization=False,
        stop_recovery=False,
        event_created_at=EVENT_CREATED_AT,
        processed_at=PROCESSED_AT,
    )


def optional_scalar_result(
    value: PaymentStateTransition | None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def required_scalar_result(
    value: PaymentAttempt,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


@pytest.mark.asyncio
async def test_projects_new_event_exactly_once() -> None:
    attempt = make_attempt()
    session = AsyncMock(spec=AsyncSession)

    session.execute.side_effect = [
        optional_scalar_result(None),
        MagicMock(),
        required_scalar_result(attempt),
        optional_scalar_result(None),
    ]

    result = await project_payment_lifecycle_event(
        session,
        make_event(),
        processed_at=PROCESSED_AT,
    )

    assert result.duplicate is False
    assert result.payment_attempt_id == ATTEMPT_ID
    assert result.state is PaymentState.FAILED
    assert result.state_version == 1
    assert result.outcome is PaymentTransitionOutcome.APPLIED
    assert result.reason is PaymentTransitionReason.INITIALIZED

    session.add.assert_called_once()
    added_transition = session.add.call_args.args[0]

    assert isinstance(
        added_transition,
        PaymentStateTransition,
    )
    assert added_transition.webhook_event_id == WEBHOOK_ID

    assert session.execute.await_count == 4
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_existing_projection_for_replayed_webhook() -> None:
    existing_transition = make_existing_transition()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        existing_transition,
    )

    result = await project_payment_lifecycle_event(
        session,
        make_event(),
        processed_at=PROCESSED_AT,
    )

    assert result.duplicate is True
    assert result.payment_attempt_id == ATTEMPT_ID
    assert result.state is PaymentState.FAILED
    assert result.state_version == 1
    assert result.outcome is PaymentTransitionOutcome.APPLIED
    assert result.reason is PaymentTransitionReason.INITIALIZED

    session.execute.assert_awaited_once()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_rechecks_idempotency_after_payment_lock() -> None:
    attempt = make_attempt(
        state=PaymentState.FAILED,
        state_version=1,
    )
    existing_transition = make_existing_transition()
    session = AsyncMock(spec=AsyncSession)

    session.execute.side_effect = [
        optional_scalar_result(None),
        MagicMock(),
        required_scalar_result(attempt),
        optional_scalar_result(existing_transition),
    ]

    result = await project_payment_lifecycle_event(
        session,
        make_event(),
        processed_at=PROCESSED_AT,
    )

    assert result.duplicate is True
    assert attempt.state_version == 1
    assert session.execute.await_count == 4
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_conflict_is_raised_before_transition_persistence() -> None:
    attempt = make_attempt(
        state=PaymentState.FAILED,
        state_version=1,
    )
    session = AsyncMock(spec=AsyncSession)

    session.execute.side_effect = [
        optional_scalar_result(None),
        MagicMock(),
        required_scalar_result(attempt),
        optional_scalar_result(None),
    ]

    with pytest.raises(
        PaymentProjectionConflictError,
        match="amount",
    ):
        await project_payment_lifecycle_event(
            session,
            make_event(
                state=PaymentState.AUTHORIZED,
                amount_minor=75_000,
            ),
            processed_at=PROCESSED_AT,
        )

    assert attempt.current_state == PaymentState.FAILED.value
    assert attempt.state_version == 1
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
