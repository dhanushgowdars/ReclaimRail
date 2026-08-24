from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import (
    PaymentAttempt,
    PaymentStateTransition,
)
from app.domain.payments import (
    PaymentLifecycleEvent,
    PaymentState,
    PaymentTransitionDecision,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
    decide_payment_transition,
)


class PaymentProjectionConflictError(ValueError):
    """Raised when events disagree about immutable payment identity."""


@dataclass(frozen=True, slots=True)
class PaymentProjectionResult:
    payment_attempt_id: UUID
    webhook_event_id: UUID
    state: PaymentState
    state_version: int
    outcome: PaymentTransitionOutcome
    reason: PaymentTransitionReason
    duplicate: bool


def validate_payment_identity(
    attempt: PaymentAttempt,
    event: PaymentLifecycleEvent,
) -> None:
    if attempt.provider != event.provider:
        raise PaymentProjectionConflictError(
            "Payment provider does not match the existing projection",
        )

    if attempt.provider_payment_id != event.payment_id:
        raise PaymentProjectionConflictError(
            "Payment identifier does not match the existing projection",
        )

    if attempt.amount_minor != event.amount_minor:
        raise PaymentProjectionConflictError(
            "Payment amount does not match the existing projection",
        )

    if attempt.currency != event.currency:
        raise PaymentProjectionConflictError(
            "Payment currency does not match the existing projection",
        )

    if (
        attempt.account_id is not None
        and event.account_id is not None
        and attempt.account_id != event.account_id
    ):
        raise PaymentProjectionConflictError(
            "Payment account does not match the existing projection",
        )

    if (
        attempt.provider_order_id is not None
        and event.order_id is not None
        and attempt.provider_order_id != event.order_id
    ):
        raise PaymentProjectionConflictError(
            "Payment order does not match the existing projection",
        )


def determine_recovery_stop_reason(
    decision: PaymentTransitionDecision,
) -> str | None:
    if not decision.stop_recovery:
        return None

    if decision.late_authorization:
        return "late_authorization"

    return f"state_{decision.next_state.value}"


def apply_applied_transition(
    attempt: PaymentAttempt,
    event: PaymentLifecycleEvent,
    decision: PaymentTransitionDecision,
    *,
    processed_at: datetime,
) -> None:
    attempt.account_id = event.account_id or attempt.account_id
    attempt.provider_order_id = event.order_id or attempt.provider_order_id
    attempt.method = event.method or attempt.method
    attempt.payment_created_at = min(
        attempt.payment_created_at,
        event.payment_created_at,
    )

    attempt.current_state = decision.next_state.value
    attempt.state_version += 1
    attempt.state_provider_event_id = event.provider_event_id
    attempt.state_webhook_event_id = event.webhook_event_id
    attempt.state_event_created_at = event.event_created_at
    attempt.updated_at = processed_at

    if decision.next_state is PaymentState.FAILED:
        attempt.error_code = event.error_code
        attempt.error_description = event.error_description
        attempt.error_source = event.error_source
        attempt.error_step = event.error_step
        attempt.error_reason = event.error_reason

        attempt.recovery_eligible = True
        attempt.recovery_stopped_at = None
        attempt.recovery_stop_reason = None
        return

    attempt.error_code = None
    attempt.error_description = None
    attempt.error_source = None
    attempt.error_step = None
    attempt.error_reason = None
    attempt.recovery_eligible = False

    if decision.stop_recovery:
        if attempt.recovery_stopped_at is None:
            attempt.recovery_stopped_at = processed_at

        if attempt.recovery_stop_reason is None or decision.late_authorization:
            attempt.recovery_stop_reason = determine_recovery_stop_reason(
                decision,
            )

    if decision.late_authorization:
        attempt.late_authorization_detected_at = event.event_created_at


def apply_payment_event_to_projection(
    attempt: PaymentAttempt,
    event: PaymentLifecycleEvent,
    *,
    processed_at: datetime,
) -> PaymentStateTransition:
    """Apply one normalized event and return its immutable audit record."""
    validate_payment_identity(
        attempt,
        event,
    )

    try:
        current_state = PaymentState(attempt.current_state)
    except ValueError as error:
        raise PaymentProjectionConflictError(
            "Existing payment projection contains an invalid state",
        ) from error

    decision = decide_payment_transition(
        current_state,
        event.state,
    )

    if decision.applied:
        apply_applied_transition(
            attempt,
            event,
            decision,
            processed_at=processed_at,
        )

    return PaymentStateTransition(
        payment_attempt_id=attempt.id,
        webhook_event_id=event.webhook_event_id,
        provider_event_id=event.provider_event_id,
        event_type=event.event_type,
        previous_state=decision.previous_state.value,
        incoming_state=event.state.value,
        resulting_state=decision.next_state.value,
        resulting_version=attempt.state_version,
        outcome=decision.outcome.value,
        reason=decision.reason.value,
        late_authorization=decision.late_authorization,
        stop_recovery=decision.stop_recovery,
        event_created_at=event.event_created_at,
        processed_at=processed_at,
    )


def result_from_transition(
    transition: PaymentStateTransition,
    *,
    duplicate: bool,
) -> PaymentProjectionResult:
    try:
        state = PaymentState(transition.resulting_state)
        outcome = PaymentTransitionOutcome(transition.outcome)
        reason = PaymentTransitionReason(transition.reason)
    except ValueError as error:
        raise PaymentProjectionConflictError(
            "Stored payment transition contains an invalid value",
        ) from error

    return PaymentProjectionResult(
        payment_attempt_id=transition.payment_attempt_id,
        webhook_event_id=transition.webhook_event_id,
        state=state,
        state_version=transition.resulting_version,
        outcome=outcome,
        reason=reason,
        duplicate=duplicate,
    )


async def find_existing_transition(
    session: AsyncSession,
    webhook_event_id: UUID,
) -> PaymentStateTransition | None:
    statement = select(PaymentStateTransition).where(
        PaymentStateTransition.webhook_event_id == webhook_event_id,
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def create_payment_attempt_if_missing(
    session: AsyncSession,
    event: PaymentLifecycleEvent,
    *,
    processed_at: datetime,
) -> None:
    statement = (
        insert(PaymentAttempt)
        .values(
            id=uuid4(),
            provider=event.provider,
            provider_payment_id=event.payment_id,
            account_id=event.account_id,
            provider_order_id=event.order_id,
            amount_minor=event.amount_minor,
            currency=event.currency,
            method=event.method,
            payment_created_at=event.payment_created_at,
            current_state=PaymentState.UNKNOWN.value,
            state_version=0,
            state_provider_event_id=event.provider_event_id,
            state_webhook_event_id=event.webhook_event_id,
            state_event_created_at=event.event_created_at,
            error_code=None,
            error_description=None,
            error_source=None,
            error_step=None,
            error_reason=None,
            recovery_eligible=False,
            recovery_stopped_at=None,
            recovery_stop_reason=None,
            late_authorization_detected_at=None,
            created_at=processed_at,
            updated_at=processed_at,
        )
        .on_conflict_do_nothing(
            constraint="uq_payment_attempts_provider_payment_id",
        )
    )

    await session.execute(statement)


async def lock_payment_attempt(
    session: AsyncSession,
    event: PaymentLifecycleEvent,
) -> PaymentAttempt:
    statement = (
        select(PaymentAttempt)
        .where(
            PaymentAttempt.provider == event.provider,
            PaymentAttempt.provider_payment_id == event.payment_id,
        )
        .with_for_update()
    )

    result = await session.execute(statement)
    return result.scalar_one()


async def project_payment_lifecycle_event(
    session: AsyncSession,
    event: PaymentLifecycleEvent,
    *,
    processed_at: datetime,
) -> PaymentProjectionResult:
    """
    Persist one payment event exactly once.

    The caller owns the surrounding transaction and must commit or roll back.
    """
    existing_transition = await find_existing_transition(
        session,
        event.webhook_event_id,
    )

    if existing_transition is not None:
        return result_from_transition(
            existing_transition,
            duplicate=True,
        )

    await create_payment_attempt_if_missing(
        session,
        event,
        processed_at=processed_at,
    )

    attempt = await lock_payment_attempt(
        session,
        event,
    )

    existing_transition = await find_existing_transition(
        session,
        event.webhook_event_id,
    )

    if existing_transition is not None:
        return result_from_transition(
            existing_transition,
            duplicate=True,
        )

    transition = apply_payment_event_to_projection(
        attempt,
        event,
        processed_at=processed_at,
    )

    session.add(transition)
    await session.flush()

    return result_from_transition(
        transition,
        duplicate=False,
    )
