from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.db.models.payment import PaymentAttempt
from app.domain.payments import (
    PaymentLifecycleEvent,
    PaymentState,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
)
from app.services.payment_projector import (
    PaymentProjectionConflictError,
    apply_payment_event_to_projection,
)

ATTEMPT_ID = UUID("10000000-0000-0000-0000-000000000001")
EXISTING_WEBHOOK_ID = UUID("20000000-0000-0000-0000-000000000001")
FAILED_WEBHOOK_ID = UUID("20000000-0000-0000-0000-000000000002")
AUTHORIZED_WEBHOOK_ID = UUID("20000000-0000-0000-0000-000000000003")
REGRESSION_WEBHOOK_ID = UUID("20000000-0000-0000-0000-000000000004")

PAYMENT_ID = "pay_reclaimrail_projector_001"
ORDER_ID = "order_reclaimrail_projector_001"

PAYMENT_CREATED_AT = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
EXISTING_EVENT_AT = datetime(2026, 8, 24, 8, 1, tzinfo=UTC)
FAILED_EVENT_AT = datetime(2026, 8, 24, 8, 2, tzinfo=UTC)
AUTHORIZED_EVENT_AT = datetime(2026, 8, 24, 8, 4, tzinfo=UTC)
PROCESSED_AT = datetime(2026, 8, 24, 8, 5, tzinfo=UTC)


def make_event(
    state: PaymentState,
    *,
    webhook_event_id: UUID,
    provider_event_id: str,
    event_created_at: datetime,
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
        webhook_event_id=webhook_event_id,
        provider_event_id=provider_event_id,
        provider="razorpay",
        account_id="acc_reclaimrail_test",
        event_type=event_types[state],
        payment_id=PAYMENT_ID,
        order_id=ORDER_ID,
        state=state,
        amount_minor=amount_minor,
        currency="INR",
        method="upi",
        event_created_at=event_created_at,
        payment_created_at=PAYMENT_CREATED_AT,
        error_code="BAD_REQUEST_ERROR" if is_failure else None,
        error_description="Payment was declined" if is_failure else None,
        error_source="customer" if is_failure else None,
        error_step="payment_authentication" if is_failure else None,
        error_reason="payment_failed" if is_failure else None,
    )


def make_attempt(
    current_state: PaymentState,
    *,
    state_version: int,
) -> PaymentAttempt:
    recovery_stopped = current_state in {
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
        PaymentState.REFUNDED,
    }

    return PaymentAttempt(
        id=ATTEMPT_ID,
        provider="razorpay",
        provider_payment_id=PAYMENT_ID,
        account_id="acc_reclaimrail_test",
        provider_order_id=ORDER_ID,
        amount_minor=50_000,
        currency="INR",
        method="upi",
        payment_created_at=PAYMENT_CREATED_AT,
        current_state=current_state.value,
        state_version=state_version,
        state_provider_event_id="evt_existing",
        state_webhook_event_id=EXISTING_WEBHOOK_ID,
        state_event_created_at=EXISTING_EVENT_AT,
        error_code=("BAD_REQUEST_ERROR" if current_state is PaymentState.FAILED else None),
        error_description=(
            "Payment was declined" if current_state is PaymentState.FAILED else None
        ),
        error_source=("customer" if current_state is PaymentState.FAILED else None),
        error_step=("payment_authentication" if current_state is PaymentState.FAILED else None),
        error_reason=("payment_failed" if current_state is PaymentState.FAILED else None),
        recovery_eligible=current_state is PaymentState.FAILED,
        recovery_stopped_at=PROCESSED_AT if recovery_stopped else None,
        recovery_stop_reason=("state_already_safe" if recovery_stopped else None),
        late_authorization_detected_at=None,
        created_at=EXISTING_EVENT_AT,
        updated_at=EXISTING_EVENT_AT,
    )


def test_initial_failure_becomes_recovery_eligible() -> None:
    attempt = make_attempt(
        PaymentState.UNKNOWN,
        state_version=0,
    )
    event = make_event(
        PaymentState.FAILED,
        webhook_event_id=FAILED_WEBHOOK_ID,
        provider_event_id="evt_payment_failed",
        event_created_at=FAILED_EVENT_AT,
    )

    transition = apply_payment_event_to_projection(
        attempt,
        event,
        processed_at=PROCESSED_AT,
    )

    assert attempt.current_state == PaymentState.FAILED.value
    assert attempt.state_version == 1
    assert attempt.state_provider_event_id == "evt_payment_failed"
    assert attempt.state_webhook_event_id == FAILED_WEBHOOK_ID
    assert attempt.recovery_eligible is True
    assert attempt.recovery_stopped_at is None

    assert transition.previous_state == PaymentState.UNKNOWN.value
    assert transition.incoming_state == PaymentState.FAILED.value
    assert transition.resulting_state == PaymentState.FAILED.value
    assert transition.resulting_version == 1
    assert transition.outcome == PaymentTransitionOutcome.APPLIED.value
    assert transition.reason == PaymentTransitionReason.INITIALIZED.value
    assert transition.stop_recovery is False


def test_late_authorization_stops_recovery() -> None:
    attempt = make_attempt(
        PaymentState.FAILED,
        state_version=1,
    )
    event = make_event(
        PaymentState.AUTHORIZED,
        webhook_event_id=AUTHORIZED_WEBHOOK_ID,
        provider_event_id="evt_payment_authorized",
        event_created_at=AUTHORIZED_EVENT_AT,
    )

    transition = apply_payment_event_to_projection(
        attempt,
        event,
        processed_at=PROCESSED_AT,
    )

    assert attempt.current_state == PaymentState.AUTHORIZED.value
    assert attempt.state_version == 2
    assert attempt.recovery_eligible is False
    assert attempt.recovery_stopped_at == PROCESSED_AT
    assert attempt.recovery_stop_reason == "late_authorization"
    assert attempt.late_authorization_detected_at == AUTHORIZED_EVENT_AT

    assert attempt.error_code is None
    assert attempt.error_description is None
    assert transition.late_authorization is True
    assert transition.stop_recovery is True
    assert transition.reason == PaymentTransitionReason.LATE_AUTHORIZATION.value


def test_out_of_order_event_is_audited_without_regression() -> None:
    attempt = make_attempt(
        PaymentState.CAPTURED,
        state_version=2,
    )
    original_provider_event_id = attempt.state_provider_event_id
    original_webhook_event_id = attempt.state_webhook_event_id

    event = make_event(
        PaymentState.AUTHORIZED,
        webhook_event_id=REGRESSION_WEBHOOK_ID,
        provider_event_id="evt_stale_authorized",
        event_created_at=AUTHORIZED_EVENT_AT,
    )

    transition = apply_payment_event_to_projection(
        attempt,
        event,
        processed_at=PROCESSED_AT,
    )

    assert attempt.current_state == PaymentState.CAPTURED.value
    assert attempt.state_version == 2
    assert attempt.state_provider_event_id == original_provider_event_id
    assert attempt.state_webhook_event_id == original_webhook_event_id
    assert attempt.recovery_eligible is False

    assert transition.outcome == PaymentTransitionOutcome.IGNORED.value
    assert transition.reason == PaymentTransitionReason.REGRESSION_BLOCKED.value
    assert transition.resulting_state == PaymentState.CAPTURED.value
    assert transition.resulting_version == 2
    assert transition.stop_recovery is True


def test_duplicate_state_is_audited_without_version_increment() -> None:
    attempt = make_attempt(
        PaymentState.FAILED,
        state_version=1,
    )
    event = make_event(
        PaymentState.FAILED,
        webhook_event_id=FAILED_WEBHOOK_ID,
        provider_event_id="evt_duplicate_failure_state",
        event_created_at=FAILED_EVENT_AT,
    )

    transition = apply_payment_event_to_projection(
        attempt,
        event,
        processed_at=PROCESSED_AT,
    )

    assert attempt.current_state == PaymentState.FAILED.value
    assert attempt.state_version == 1
    assert attempt.recovery_eligible is True
    assert transition.outcome == PaymentTransitionOutcome.IGNORED.value
    assert transition.reason == PaymentTransitionReason.DUPLICATE_STATE.value
    assert transition.resulting_version == 1


def test_conflicting_payment_amount_is_rejected() -> None:
    attempt = make_attempt(
        PaymentState.FAILED,
        state_version=1,
    )
    event = make_event(
        PaymentState.AUTHORIZED,
        webhook_event_id=AUTHORIZED_WEBHOOK_ID,
        provider_event_id="evt_conflicting_amount",
        event_created_at=AUTHORIZED_EVENT_AT,
        amount_minor=75_000,
    )

    with pytest.raises(
        PaymentProjectionConflictError,
        match="amount",
    ):
        apply_payment_event_to_projection(
            attempt,
            event,
            processed_at=PROCESSED_AT,
        )

    assert attempt.current_state == PaymentState.FAILED.value
    assert attempt.state_version == 1
