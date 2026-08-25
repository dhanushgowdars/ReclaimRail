from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAuditActor,
    RecoveryCase,
)
from app.domain.payments import STOP_RECOVERY_STATES, PaymentState
from app.domain.recovery import RecoveryActionType, RecoveryCaseStatus
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkStatus,
)
from app.services.recovery_action_executor import build_payment_link_reference_id
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)

SessionFactory = async_sessionmaker[AsyncSession]

DEFAULT_COMPENSATION_RETRY_DELAY = timedelta(minutes=1)

PENDING_RECOVERY_ACTION_STATUSES = frozenset(
    {
        RecoveryActionStatus.ALLOWED.value,
        RecoveryActionStatus.SCHEDULED.value,
        RecoveryActionStatus.EXECUTING.value,
        RecoveryActionStatus.FAILED.value,
    },
)


class RecoveryCompensationDisposition(StrEnum):
    CANCELLED = "cancelled"
    ALREADY_CANCELLED = "already_cancelled"
    ESCALATED = "escalated"


class RecoveryCompensationCaseNotFoundError(LookupError):
    pass


class RecoveryCompensationPaymentNotFoundError(LookupError):
    pass


class RecoveryCompensationPaymentLinkActionNotFoundError(LookupError):
    pass


class RecoveryCompensationNotRequiredError(ValueError):
    pass


class RecoveryCompensationProviderFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class PreparedRecoveryCompensation:
    recovery_case_id: UUID
    payment_attempt_id: UUID
    payment_link_action_id: UUID
    payment_link_id: str
    reference_id: str


@dataclass(frozen=True, slots=True)
class RecoveryCompensationResult:
    recovery_case_id: UUID
    disposition: RecoveryCompensationDisposition
    payment_link_id: str | None
    provider_status: RazorpayPaymentLinkStatus | None


@dataclass(frozen=True, slots=True)
class RecoveryCompensationPreparation:
    prepared: PreparedRecoveryCompensation | None = None
    terminal_result: RecoveryCompensationResult | None = None

    def __post_init__(self) -> None:
        if (self.prepared is None) == (self.terminal_result is None):
            raise ValueError(
                "Compensation preparation requires exactly one result",
            )


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Recovery compensation time must be timezone-aware",
        )


def _payment_requires_recovery_stop(
    payment_attempt: PaymentAttempt,
) -> bool:
    try:
        payment_state = PaymentState(
            payment_attempt.current_state,
        )
    except ValueError as error:
        raise RecoveryCompensationNotRequiredError(
            "Payment projection contains an invalid state",
        ) from error

    return (
        payment_state in STOP_RECOVERY_STATES
        or payment_attempt.late_authorization_detected_at is not None
    )


async def prepare_late_authorization_compensation(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
    detected_at: datetime,
) -> RecoveryCompensationPreparation:
    _require_timezone_aware(detected_at)

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryCompensationCaseNotFoundError(
            f"Recovery case {recovery_case_id} does not exist",
        )

    if (
        recovery_case.status == RecoveryCaseStatus.CANCELLED.value
        and recovery_case.active_payment_link_id is None
    ):
        return RecoveryCompensationPreparation(
            terminal_result=RecoveryCompensationResult(
                recovery_case_id=recovery_case.id,
                disposition=(RecoveryCompensationDisposition.ALREADY_CANCELLED),
                payment_link_id=None,
                provider_status=(RazorpayPaymentLinkStatus.CANCELLED),
            ),
        )

    payment_result = await session.execute(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.id == recovery_case.payment_attempt_id,
        )
        .with_for_update(),
    )
    payment_attempt = payment_result.scalar_one_or_none()

    if payment_attempt is None:
        raise RecoveryCompensationPaymentNotFoundError(
            f"Payment attempt {recovery_case.payment_attempt_id} does not exist",
        )

    if not _payment_requires_recovery_stop(
        payment_attempt,
    ):
        raise RecoveryCompensationNotRequiredError(
            f"Payment {payment_attempt.id} does not require recovery compensation",
        )

    payment_link_id = recovery_case.active_payment_link_id

    if payment_link_id is None:
        recovery_case.status = RecoveryCaseStatus.CANCELLED.value
        recovery_case.closed_at = detected_at
        recovery_case.close_reason = "payment_completed_without_active_recovery_link"
        recovery_case.next_action_at = None
        recovery_case.late_authorization_detected_at = (
            payment_attempt.late_authorization_detected_at or detected_at
        )
        recovery_case.version += 1

        await append_recovery_audit_event(
            session,
            recovery_case_id=recovery_case.id,
            request=RecoveryAuditAppendRequest(
                event_type=("recovery.late_authorization.closed_without_link"),
                actor_type=RecoveryAuditActor.SYSTEM,
                event_data={
                    "payment_attempt_id": str(
                        payment_attempt.id,
                    ),
                    "payment_state": (payment_attempt.current_state),
                },
                occurred_at=detected_at,
            ),
        )

        return RecoveryCompensationPreparation(
            terminal_result=RecoveryCompensationResult(
                recovery_case_id=recovery_case.id,
                disposition=(RecoveryCompensationDisposition.CANCELLED),
                payment_link_id=None,
                provider_status=None,
            ),
        )

    action_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.recovery_case_id == recovery_case.id,
            RecoveryAction.action_type == RecoveryActionType.CREATE_PAYMENT_LINK.value,
            RecoveryAction.status == RecoveryActionStatus.SUCCEEDED.value,
            RecoveryAction.provider_action_id == payment_link_id,
        )
        .with_for_update(),
    )
    payment_link_action = action_result.scalar_one_or_none()

    if payment_link_action is None:
        raise (
            RecoveryCompensationPaymentLinkActionNotFoundError(
                f"Active Payment Link {payment_link_id} has no successful recovery action",
            )
        )

    actions_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.recovery_case_id == recovery_case.id,
        )
        .with_for_update(),
    )
    actions = tuple(
        actions_result.scalars().all(),
    )
    cancelled_action_ids: list[str] = []

    for action in actions:
        if action.id == payment_link_action.id:
            continue

        if action.status not in PENDING_RECOVERY_ACTION_STATUSES:
            continue

        action.status = RecoveryActionStatus.CANCELLED.value
        action.completed_at = detected_at
        action.last_error = None
        cancelled_action_ids.append(
            str(action.id),
        )

    first_detection = recovery_case.late_authorization_detected_at is None

    recovery_case.status = RecoveryCaseStatus.EXECUTING.value
    recovery_case.late_authorization_detected_at = (
        payment_attempt.late_authorization_detected_at or detected_at
    )
    recovery_case.next_action_at = detected_at
    recovery_case.closed_at = None
    recovery_case.close_reason = None
    recovery_case.version += 1

    if first_detection:
        await append_recovery_audit_event(
            session,
            recovery_case_id=recovery_case.id,
            request=RecoveryAuditAppendRequest(
                event_type=("recovery.late_authorization.detected"),
                actor_type=RecoveryAuditActor.SYSTEM,
                recovery_action_id=(payment_link_action.id),
                agent_run_id=(payment_link_action.agent_run_id),
                event_data={
                    "payment_attempt_id": str(
                        payment_attempt.id,
                    ),
                    "payment_state": (payment_attempt.current_state),
                    "payment_link_id": payment_link_id,
                    "cancelled_action_ids": (cancelled_action_ids),
                },
                occurred_at=detected_at,
            ),
        )

    return RecoveryCompensationPreparation(
        prepared=PreparedRecoveryCompensation(
            recovery_case_id=recovery_case.id,
            payment_attempt_id=payment_attempt.id,
            payment_link_action_id=(payment_link_action.id),
            payment_link_id=payment_link_id,
            reference_id=build_payment_link_reference_id(
                payment_link_action.id,
            ),
        ),
    )


def _validate_provider_link(
    prepared: PreparedRecoveryCompensation,
    payment_link: RazorpayPaymentLink,
) -> None:
    if payment_link.payment_link_id != prepared.payment_link_id:
        raise RazorpayPaymentLinkProviderError(
            "Razorpay Payment Link ID did not match the active recovery link",
            retryable=False,
        )

    if payment_link.reference_id != prepared.reference_id:
        raise RazorpayPaymentLinkProviderError(
            "Razorpay Payment Link reference did not match the recovery action",
            retryable=False,
        )


async def complete_late_authorization_compensation(
    session: AsyncSession,
    *,
    prepared: PreparedRecoveryCompensation,
    payment_link: RazorpayPaymentLink,
    completed_at: datetime,
) -> RecoveryCompensationResult:
    _require_timezone_aware(completed_at)
    _validate_provider_link(
        prepared,
        payment_link,
    )

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == prepared.recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryCompensationCaseNotFoundError(
            f"Recovery case {prepared.recovery_case_id} does not exist",
        )

    if (
        recovery_case.status == RecoveryCaseStatus.CANCELLED.value
        and recovery_case.active_payment_link_id is None
    ):
        return RecoveryCompensationResult(
            recovery_case_id=recovery_case.id,
            disposition=(RecoveryCompensationDisposition.ALREADY_CANCELLED),
            payment_link_id=(payment_link.payment_link_id),
            provider_status=payment_link.status,
        )

    action_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == prepared.payment_link_action_id,
        )
        .with_for_update(),
    )
    payment_link_action = action_result.scalar_one_or_none()

    if payment_link_action is None:
        raise (
            RecoveryCompensationPaymentLinkActionNotFoundError(
                f"Recovery action {prepared.payment_link_action_id} does not exist",
            )
        )

    if payment_link.status in {
        RazorpayPaymentLinkStatus.PAID,
        RazorpayPaymentLinkStatus.PARTIALLY_PAID,
    }:
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None
        recovery_case.closed_at = None
        recovery_case.close_reason = "possible_duplicate_payment_requires_review"
        recovery_case.version += 1

        payment_link_action.provider_action_status = payment_link.status.value

        await append_recovery_audit_event(
            session,
            recovery_case_id=recovery_case.id,
            request=RecoveryAuditAppendRequest(
                event_type=("action.payment_link.cancellation_escalated"),
                actor_type=RecoveryAuditActor.RAZORPAY,
                recovery_action_id=(payment_link_action.id),
                agent_run_id=(payment_link_action.agent_run_id),
                event_data={
                    "payment_link_id": (payment_link.payment_link_id),
                    "provider_status": (payment_link.status.value),
                    "reason": ("payment_link_already_received_payment"),
                },
                occurred_at=completed_at,
            ),
        )

        return RecoveryCompensationResult(
            recovery_case_id=recovery_case.id,
            disposition=(RecoveryCompensationDisposition.ESCALATED),
            payment_link_id=(payment_link.payment_link_id),
            provider_status=payment_link.status,
        )

    if payment_link.status not in {
        RazorpayPaymentLinkStatus.CANCELLED,
        RazorpayPaymentLinkStatus.EXPIRED,
    }:
        raise RazorpayPaymentLinkProviderError(
            "Razorpay Payment Link was not cancelled",
            retryable=True,
        )

    payment_link_action.provider_action_status = payment_link.status.value
    payment_link_action.last_error = None

    recovery_case.status = RecoveryCaseStatus.CANCELLED.value
    recovery_case.active_payment_link_id = None
    recovery_case.next_action_at = None
    recovery_case.closed_at = completed_at
    recovery_case.close_reason = "late_authorization_payment_link_cancelled"
    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type=("action.payment_link.cancelled"),
            actor_type=RecoveryAuditActor.RAZORPAY,
            recovery_action_id=(payment_link_action.id),
            agent_run_id=(payment_link_action.agent_run_id),
            event_data={
                "payment_link_id": (payment_link.payment_link_id),
                "provider_status": (payment_link.status.value),
                "reason": "late_authorization",
            },
            occurred_at=completed_at,
        ),
    )

    return RecoveryCompensationResult(
        recovery_case_id=recovery_case.id,
        disposition=(RecoveryCompensationDisposition.CANCELLED),
        payment_link_id=payment_link.payment_link_id,
        provider_status=payment_link.status,
    )


async def record_late_authorization_compensation_failure(
    session: AsyncSession,
    *,
    prepared: PreparedRecoveryCompensation,
    error: RazorpayPaymentLinkProviderError,
    failed_at: datetime,
    retry_delay: timedelta = (DEFAULT_COMPENSATION_RETRY_DELAY),
) -> None:
    _require_timezone_aware(failed_at)

    if retry_delay.total_seconds() <= 0:
        raise ValueError(
            "Recovery compensation retry delay must be positive",
        )

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == prepared.recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryCompensationCaseNotFoundError(
            f"Recovery case {prepared.recovery_case_id} does not exist",
        )

    action_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == prepared.payment_link_action_id,
        )
        .with_for_update(),
    )
    payment_link_action = action_result.scalar_one_or_none()

    if payment_link_action is None:
        raise (
            RecoveryCompensationPaymentLinkActionNotFoundError(
                f"Recovery action {prepared.payment_link_action_id} does not exist",
            )
        )

    safe_error = (
        "RazorpayPaymentLinkProviderError"
        f"(retryable={error.retryable}, "
        f"status_code={error.status_code})"
    )

    payment_link_action.last_error = safe_error
    recovery_case.status = RecoveryCaseStatus.EXECUTING.value
    recovery_case.next_action_at = failed_at + retry_delay
    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type=("action.payment_link.cancellation_failed"),
            actor_type=RecoveryAuditActor.RAZORPAY,
            recovery_action_id=(payment_link_action.id),
            agent_run_id=(payment_link_action.agent_run_id),
            event_data={
                "payment_link_id": (prepared.payment_link_id),
                "retryable": error.retryable,
                "status_code": error.status_code,
                "retry_at": (recovery_case.next_action_at),
            },
            occurred_at=failed_at,
        ),
    )


async def compensate_late_authorized_recovery(
    session_factory: SessionFactory,
    *,
    recovery_case_id: UUID,
    provider: RazorpayPaymentLinkProvider,
    compensated_at: datetime,
    retry_delay: timedelta = (DEFAULT_COMPENSATION_RETRY_DELAY),
) -> RecoveryCompensationResult:
    _require_timezone_aware(compensated_at)

    async with session_factory.begin() as session:
        preparation = await prepare_late_authorization_compensation(
            session,
            recovery_case_id=recovery_case_id,
            detected_at=compensated_at,
        )

    if preparation.terminal_result is not None:
        return preparation.terminal_result

    prepared = preparation.prepared

    if prepared is None:
        raise RuntimeError(
            "Recovery compensation preparation was empty",
        )

    try:
        payment_link = await provider.find_payment_link_by_reference(
            prepared.reference_id,
        )

        if payment_link is None:
            payment_link = await provider.cancel_payment_link(
                prepared.payment_link_id,
            )
        else:
            _validate_provider_link(
                prepared,
                payment_link,
            )

            if payment_link.status is RazorpayPaymentLinkStatus.CREATED:
                payment_link = await provider.cancel_payment_link(
                    payment_link.payment_link_id,
                )

    except RazorpayPaymentLinkProviderError as error:
        async with session_factory.begin() as session:
            await record_late_authorization_compensation_failure(
                session,
                prepared=prepared,
                error=error,
                failed_at=compensated_at,
                retry_delay=retry_delay,
            )

        raise RecoveryCompensationProviderFailure(
            "Razorpay Payment Link compensation failed",
            retryable=error.retryable,
            status_code=error.status_code,
        ) from error

    async with session_factory.begin() as session:
        return await complete_late_authorization_compensation(
            session,
            prepared=prepared,
            payment_link=payment_link,
            completed_at=compensated_at,
        )
