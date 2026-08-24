from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class PaymentState(StrEnum):
    UNKNOWN = "unknown"
    CREATED = "created"
    FAILED = "failed"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"


class PaymentTransitionOutcome(StrEnum):
    APPLIED = "applied"
    IGNORED = "ignored"


class PaymentTransitionReason(StrEnum):
    INITIALIZED = "initialized"
    PROGRESSED = "progressed"
    LATE_AUTHORIZATION = "late_authorization"
    DUPLICATE_STATE = "duplicate_state"
    REGRESSION_BLOCKED = "regression_blocked"
    TERMINAL_STATE = "terminal_state"
    INVALID_TARGET = "invalid_target"


STOP_RECOVERY_STATES: Final[frozenset[PaymentState]] = frozenset(
    {
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
        PaymentState.REFUNDED,
    },
)

ALLOWED_TRANSITIONS: Final[Mapping[PaymentState, frozenset[PaymentState]]] = {
    PaymentState.UNKNOWN: frozenset(
        {
            PaymentState.CREATED,
            PaymentState.FAILED,
            PaymentState.AUTHORIZED,
            PaymentState.CAPTURED,
            PaymentState.REFUNDED,
        },
    ),
    PaymentState.CREATED: frozenset(
        {
            PaymentState.FAILED,
            PaymentState.AUTHORIZED,
            PaymentState.CAPTURED,
            PaymentState.REFUNDED,
        },
    ),
    PaymentState.FAILED: frozenset(
        {
            PaymentState.AUTHORIZED,
            PaymentState.CAPTURED,
            PaymentState.REFUNDED,
        },
    ),
    PaymentState.AUTHORIZED: frozenset(
        {
            PaymentState.CAPTURED,
            PaymentState.REFUNDED,
        },
    ),
    PaymentState.CAPTURED: frozenset(
        {
            PaymentState.REFUNDED,
        },
    ),
    PaymentState.REFUNDED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class PaymentTransitionDecision:
    previous_state: PaymentState
    next_state: PaymentState
    outcome: PaymentTransitionOutcome
    reason: PaymentTransitionReason
    late_authorization: bool
    stop_recovery: bool

    @property
    def applied(self) -> bool:
        return self.outcome is PaymentTransitionOutcome.APPLIED


def decide_payment_transition(
    current_state: PaymentState,
    incoming_state: PaymentState,
) -> PaymentTransitionDecision:
    recovery_already_stopped = current_state in STOP_RECOVERY_STATES

    if incoming_state is PaymentState.UNKNOWN:
        return PaymentTransitionDecision(
            previous_state=current_state,
            next_state=current_state,
            outcome=PaymentTransitionOutcome.IGNORED,
            reason=PaymentTransitionReason.INVALID_TARGET,
            late_authorization=False,
            stop_recovery=recovery_already_stopped,
        )

    if incoming_state is current_state:
        return PaymentTransitionDecision(
            previous_state=current_state,
            next_state=current_state,
            outcome=PaymentTransitionOutcome.IGNORED,
            reason=PaymentTransitionReason.DUPLICATE_STATE,
            late_authorization=False,
            stop_recovery=recovery_already_stopped,
        )

    if current_state is PaymentState.REFUNDED:
        return PaymentTransitionDecision(
            previous_state=current_state,
            next_state=current_state,
            outcome=PaymentTransitionOutcome.IGNORED,
            reason=PaymentTransitionReason.TERMINAL_STATE,
            late_authorization=False,
            stop_recovery=True,
        )

    allowed_states = ALLOWED_TRANSITIONS[current_state]

    if incoming_state not in allowed_states:
        return PaymentTransitionDecision(
            previous_state=current_state,
            next_state=current_state,
            outcome=PaymentTransitionOutcome.IGNORED,
            reason=PaymentTransitionReason.REGRESSION_BLOCKED,
            late_authorization=False,
            stop_recovery=recovery_already_stopped,
        )

    late_authorization = current_state is PaymentState.FAILED and incoming_state in {
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
    }

    reason = (
        PaymentTransitionReason.LATE_AUTHORIZATION
        if late_authorization
        else (
            PaymentTransitionReason.INITIALIZED
            if current_state is PaymentState.UNKNOWN
            else PaymentTransitionReason.PROGRESSED
        )
    )

    return PaymentTransitionDecision(
        previous_state=current_state,
        next_state=incoming_state,
        outcome=PaymentTransitionOutcome.APPLIED,
        reason=reason,
        late_authorization=late_authorization,
        stop_recovery=(recovery_already_stopped or incoming_state in STOP_RECOVERY_STATES),
    )
