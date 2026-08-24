import pytest

from app.domain.payments import (
    PaymentState,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
    decide_payment_transition,
)


def test_initializes_payment_from_first_observed_failure() -> None:
    decision = decide_payment_transition(
        PaymentState.UNKNOWN,
        PaymentState.FAILED,
    )

    assert decision.applied is True
    assert decision.next_state is PaymentState.FAILED
    assert decision.reason is PaymentTransitionReason.INITIALIZED
    assert decision.stop_recovery is False


@pytest.mark.parametrize(
    "incoming_state",
    [
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
    ],
)
def test_late_success_stops_recovery(
    incoming_state: PaymentState,
) -> None:
    decision = decide_payment_transition(
        PaymentState.FAILED,
        incoming_state,
    )

    assert decision.applied is True
    assert decision.next_state is incoming_state
    assert decision.reason is PaymentTransitionReason.LATE_AUTHORIZATION
    assert decision.late_authorization is True
    assert decision.stop_recovery is True


def test_authorized_payment_progresses_to_captured() -> None:
    decision = decide_payment_transition(
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
    )

    assert decision.applied is True
    assert decision.next_state is PaymentState.CAPTURED
    assert decision.stop_recovery is True


def test_out_of_order_authorized_event_cannot_regress_capture() -> None:
    decision = decide_payment_transition(
        PaymentState.CAPTURED,
        PaymentState.AUTHORIZED,
    )

    assert decision.applied is False
    assert decision.next_state is PaymentState.CAPTURED
    assert decision.reason is PaymentTransitionReason.REGRESSION_BLOCKED
    assert decision.stop_recovery is True


def test_duplicate_state_is_idempotent() -> None:
    decision = decide_payment_transition(
        PaymentState.FAILED,
        PaymentState.FAILED,
    )

    assert decision.outcome is PaymentTransitionOutcome.IGNORED
    assert decision.reason is PaymentTransitionReason.DUPLICATE_STATE
    assert decision.next_state is PaymentState.FAILED


def test_refunded_state_is_terminal() -> None:
    decision = decide_payment_transition(
        PaymentState.REFUNDED,
        PaymentState.CAPTURED,
    )

    assert decision.applied is False
    assert decision.next_state is PaymentState.REFUNDED
    assert decision.reason is PaymentTransitionReason.TERMINAL_STATE
    assert decision.stop_recovery is True


def test_unknown_is_not_a_valid_incoming_provider_state() -> None:
    decision = decide_payment_transition(
        PaymentState.CREATED,
        PaymentState.UNKNOWN,
    )

    assert decision.applied is False
    assert decision.next_state is PaymentState.CREATED
    assert decision.reason is PaymentTransitionReason.INVALID_TARGET
