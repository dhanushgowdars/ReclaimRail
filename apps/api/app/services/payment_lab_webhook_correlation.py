from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_lab import (
    PaymentLabRun,
    PaymentLabRunStatus,
)
from app.domain.payments import PaymentLifecycleEvent, PaymentState
from app.services.payment_projector import PaymentProjectionResult


class PaymentLabWebhookCorrelationError(ValueError):
    """Raised when signed provider evidence conflicts with a Payment Lab run."""


class PaymentLabWebhookCorrelationDisposition(StrEnum):
    CORRELATED = "correlated"
    ALREADY_CURRENT = "already_current"


@dataclass(frozen=True, slots=True)
class PreparedPaymentLabWebhookCorrelation:
    payment_lab_run: PaymentLabRun


@dataclass(frozen=True, slots=True)
class PaymentLabWebhookCorrelationResult:
    payment_lab_run_id: UUID
    payment_attempt_id: UUID
    status: PaymentLabRunStatus
    disposition: PaymentLabWebhookCorrelationDisposition


def _normalized_failure_code(event: PaymentLifecycleEvent) -> str:
    value = event.error_code or event.error_reason or "payment_failed"
    return value.strip()[:64] or "payment_failed"


def _validate_run_identity(
    payment_lab_run: PaymentLabRun,
    event: PaymentLifecycleEvent,
) -> None:
    if payment_lab_run.amount_minor != event.amount_minor:
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab webhook amount does not match the provider Order",
        )

    if payment_lab_run.currency != event.currency:
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab webhook currency does not match the provider Order",
        )

    if event.method is not None and payment_lab_run.payment_method != event.method:
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab webhook method does not match the bounded run input",
        )


async def _validate_existing_payment_attempt(
    session: AsyncSession,
    payment_lab_run: PaymentLabRun,
    event: PaymentLifecycleEvent,
) -> None:
    if payment_lab_run.payment_attempt_id is None:
        return

    statement = select(PaymentAttempt).where(
        PaymentAttempt.id == payment_lab_run.payment_attempt_id,
    )
    result = await session.execute(statement)
    payment_attempt = result.scalar_one_or_none()

    if payment_attempt is None:
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab run references a missing payment attempt",
        )

    if (
        payment_attempt.provider != event.provider
        or payment_attempt.provider_payment_id != event.payment_id
        or payment_attempt.provider_order_id != event.order_id
    ):
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab run is already linked to different provider evidence",
        )


async def prepare_payment_lab_webhook_correlation(
    session: AsyncSession,
    event: PaymentLifecycleEvent,
) -> PreparedPaymentLabWebhookCorrelation | None:
    """Lock and validate a matching Payment Lab run before projection."""

    if event.provider != "razorpay" or event.order_id is None:
        return None

    statement = (
        select(PaymentLabRun)
        .where(
            PaymentLabRun.provider_order_id == event.order_id,
        )
        .with_for_update()
    )
    result = await session.execute(statement)
    payment_lab_run = result.scalar_one_or_none()

    if payment_lab_run is None:
        return None

    _validate_run_identity(
        payment_lab_run,
        event,
    )
    await _validate_existing_payment_attempt(
        session,
        payment_lab_run,
        event,
    )

    return PreparedPaymentLabWebhookCorrelation(
        payment_lab_run=payment_lab_run,
    )


def _target_run_status(
    current_status: PaymentLabRunStatus,
    payment_state: PaymentState,
) -> PaymentLabRunStatus:
    if payment_state is PaymentState.FAILED:
        if current_status in {
            PaymentLabRunStatus.CREATING,
            PaymentLabRunStatus.CHECKOUT_READY,
        }:
            return PaymentLabRunStatus.PAYMENT_ATTEMPTED

        return current_status

    if payment_state in {
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
        PaymentState.REFUNDED,
    }:
        return PaymentLabRunStatus.COMPLETED

    return current_status


def apply_payment_lab_webhook_correlation(
    prepared: PreparedPaymentLabWebhookCorrelation,
    event: PaymentLifecycleEvent,
    projection: PaymentProjectionResult,
    *,
    observed_at: datetime,
) -> PaymentLabWebhookCorrelationResult:
    """Attach projected payment truth without allowing replay regression."""

    payment_lab_run = prepared.payment_lab_run

    if (
        payment_lab_run.payment_attempt_id is not None
        and payment_lab_run.payment_attempt_id != projection.payment_attempt_id
    ):
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab projection resolved to a different payment attempt",
        )

    try:
        current_status = PaymentLabRunStatus(payment_lab_run.status)
    except ValueError as error:
        raise PaymentLabWebhookCorrelationError(
            "Payment Lab run contains an invalid status",
        ) from error

    target_status = _target_run_status(
        current_status,
        projection.state,
    )
    target_failure_code = (
        _normalized_failure_code(event) if projection.state is PaymentState.FAILED else None
    )

    changed = False

    if payment_lab_run.payment_attempt_id is None:
        payment_lab_run.payment_attempt_id = projection.payment_attempt_id
        changed = True

    if payment_lab_run.status != target_status.value:
        payment_lab_run.status = target_status.value
        changed = True

    if payment_lab_run.failure_code != target_failure_code:
        payment_lab_run.failure_code = target_failure_code
        changed = True

    if changed:
        payment_lab_run.updated_at = observed_at
        payment_lab_run.version += 1

    return PaymentLabWebhookCorrelationResult(
        payment_lab_run_id=payment_lab_run.id,
        payment_attempt_id=projection.payment_attempt_id,
        status=target_status,
        disposition=(
            PaymentLabWebhookCorrelationDisposition.CORRELATED
            if changed
            else PaymentLabWebhookCorrelationDisposition.ALREADY_CURRENT
        ),
    )
