from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_lab import PaymentLabRun
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAuditActor,
    RecoveryCase,
)
from app.domain.recovery import (
    RecoveryActionType,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPolicyOutcome,
    evaluate_recovery_proposal,
)
from app.integrations.razorpay.payment_customers import (
    RazorpayPaymentCustomerProvider,
    RazorpayPaymentCustomerProviderError,
)
from app.integrations.razorpay.payment_link_notifications import (
    RazorpayPaymentLinkNotificationError,
    RazorpayPaymentLinkNotificationMedium,
    RazorpayPaymentLinkNotificationProvider,
)
from app.integrations.resend.recovery_email import (
    ResendRecoveryEmailError,
    ResendRecoveryEmailProvider,
)
from app.services.recovery_action_executor import (
    DEFAULT_ACTION_CLAIM_TIMEOUT,
    DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
    RecoveryActionCaseNotFoundError,
    RecoveryActionExecutionDisposition,
    RecoveryActionExecutionResult,
    RecoveryActionInProgressError,
    RecoveryActionNotDueError,
    RecoveryActionNotExecutableError,
    RecoveryActionNotFoundError,
    RecoveryActionPaymentNotFoundError,
    _apply_denied_case_projection,
    _build_case_snapshot,
    _build_proposal,
    _policy_disposition,
    _policy_status,
    _require_timezone_aware,
)
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)
from app.services.recovery_incident_context import (
    load_active_recovery_incident_context,
)

SessionFactory = async_sessionmaker[AsyncSession]


class RecoveryMessageProviderFailure(RuntimeError):
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


class RecoveryMessageProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        delivery_attempted: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.delivery_attempted = delivery_attempted
        self.status_code = status_code


class RecoveryMessageExecutionDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    ALREADY_SUCCEEDED = "already_succeeded"
    POLICY_BLOCKED = "policy_blocked"
    POLICY_ESCALATED = "policy_escalated"
    POLICY_STOPPED = "policy_stopped"


@dataclass(frozen=True, slots=True)
class PreparedRecoveryMessageAction:
    action_id: UUID
    recovery_case_id: UUID
    provider_payment_id: str
    payment_link_id: str
    medium: RazorpayPaymentLinkNotificationMedium
    attempt_number: int
    direct_email_eligible: bool = False
    payment_link_url: str | None = None
    amount_minor: int = 0
    currency: str = "INR"


@dataclass(frozen=True, slots=True)
class RecoveryMessageActionPreparation:
    prepared: PreparedRecoveryMessageAction | None = None
    terminal_result: RecoveryActionExecutionResult | None = None

    def __post_init__(self) -> None:
        if (self.prepared is None) == (self.terminal_result is None):
            raise ValueError(
                "Message action preparation requires exactly one result",
            )


def _notification_medium(
    channel: str | None,
) -> RazorpayPaymentLinkNotificationMedium:
    if channel == RecoveryChannel.EMAIL.value:
        return RazorpayPaymentLinkNotificationMedium.EMAIL

    if channel == RecoveryChannel.SMS.value:
        return RazorpayPaymentLinkNotificationMedium.SMS

    raise RecoveryActionNotExecutableError(
        "Recovery message action requires a supported email or SMS channel",
    )


def _has_contact_for_medium(
    *,
    medium: RazorpayPaymentLinkNotificationMedium,
    email: str | None,
    contact: str | None,
) -> bool:
    if medium is RazorpayPaymentLinkNotificationMedium.EMAIL:
        return email is not None

    return contact is not None


async def prepare_recovery_message_action(
    session: AsyncSession,
    *,
    action_id: UUID,
    executed_at: datetime,
    claim_timeout: timedelta = DEFAULT_ACTION_CLAIM_TIMEOUT,
    maximum_attempts: int = DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
) -> RecoveryMessageActionPreparation:
    """Lock, re-evaluate and claim one approved recovery-message action."""
    _require_timezone_aware(executed_at)

    if claim_timeout <= timedelta(0):
        raise ValueError(
            "Message action claim timeout must be positive",
        )

    if maximum_attempts < 1:
        raise ValueError(
            "Message action maximum attempts must be positive",
        )

    action_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == action_id,
        )
        .with_for_update(),
    )
    action = action_result.scalar_one_or_none()

    if action is None:
        raise RecoveryActionNotFoundError(
            f"Recovery action {action_id} does not exist",
        )

    if action.action_type != RecoveryActionType.SEND_RECOVERY_MESSAGE.value:
        raise RecoveryActionNotExecutableError(
            f"Recovery action {action_id} is not a recovery-message action",
        )

    if action.status == RecoveryActionStatus.SUCCEEDED.value:
        return RecoveryMessageActionPreparation(
            terminal_result=RecoveryActionExecutionResult(
                action_id=action.id,
                recovery_case_id=action.recovery_case_id,
                disposition=RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED,
            ),
        )

    if (
        action.status == RecoveryActionStatus.SCHEDULED.value
        and action.execute_after is not None
        and action.execute_after > executed_at
    ):
        raise RecoveryActionNotDueError(
            f"Recovery action {action_id} is not due",
        )

    if action.status == RecoveryActionStatus.EXECUTING.value:
        if action.started_at is not None and executed_at < action.started_at + claim_timeout:
            raise RecoveryActionInProgressError(
                f"Recovery action {action_id} has an active execution claim",
            )
    elif action.status not in {
        RecoveryActionStatus.ALLOWED.value,
        RecoveryActionStatus.SCHEDULED.value,
        RecoveryActionStatus.FAILED.value,
    }:
        raise RecoveryActionNotExecutableError(
            f"Recovery action {action_id} cannot execute from {action.status}",
        )

    if action.execution_attempt_count >= maximum_attempts:
        raise RecoveryActionNotExecutableError(
            f"Recovery action {action_id} reached its execution-attempt limit",
        )

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == action.recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryActionCaseNotFoundError(
            f"Recovery case {action.recovery_case_id} does not exist",
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
        raise RecoveryActionPaymentNotFoundError(
            f"Payment attempt {recovery_case.payment_attempt_id} does not exist",
        )

    incident_context = await load_active_recovery_incident_context(
        session,
        source_incident_id=recovery_case.source_incident_id,
        currency=recovery_case.currency,
        payment_method=recovery_case.payment_method,
    )

    decision = evaluate_recovery_proposal(
        _build_case_snapshot(
            recovery_case,
            payment_attempt,
            incident_severity=(incident_context.severity if incident_context is not None else None),
        ),
        _build_proposal(action),
        evaluated_at=executed_at,
    )

    action.policy_outcome = decision.outcome.value
    action.policy_guardrails = [guardrail.value for guardrail in decision.guardrails]
    action.policy_explanation = decision.explanation
    action.policy_evaluated_at = decision.evaluated_at

    if decision.outcome is not RecoveryPolicyOutcome.ALLOW:
        action.status = _policy_status(
            decision.outcome,
        ).value
        action.completed_at = executed_at

        _apply_denied_case_projection(
            recovery_case,
            outcome=decision.outcome,
            executed_at=executed_at,
        )

        await append_recovery_audit_event(
            session,
            recovery_case_id=recovery_case.id,
            request=RecoveryAuditAppendRequest(
                event_type="action.execution.denied",
                actor_type=RecoveryAuditActor.POLICY,
                recovery_action_id=action.id,
                agent_run_id=action.agent_run_id,
                event_data={
                    "action_type": action.action_type,
                    "policy_outcome": decision.outcome.value,
                    "guardrails": [guardrail.value for guardrail in decision.guardrails],
                    "policy_version": action.policy_version,
                    "active_incident": (
                        {
                            "incident_id": str(incident_context.incident_id),
                            "scope": incident_context.scope,
                            "dimension_value": incident_context.dimension_value,
                            "severity": incident_context.severity.value,
                        }
                        if incident_context is not None
                        else None
                    ),
                },
                occurred_at=executed_at,
            ),
        )

        return RecoveryMessageActionPreparation(
            terminal_result=RecoveryActionExecutionResult(
                action_id=action.id,
                recovery_case_id=recovery_case.id,
                disposition=_policy_disposition(
                    decision.outcome,
                ),
            ),
        )

    if recovery_case.active_payment_link_id is None:
        raise RecoveryActionNotExecutableError(
            "Recovery message action requires an active Payment Link",
        )

    medium = _notification_medium(
        action.channel,
    )

    direct_email_eligible = False
    payment_link_url: str | None = None
    if medium is RazorpayPaymentLinkNotificationMedium.EMAIL:
        payment_lab_result = await session.execute(
            select(PaymentLabRun.test_email_contact_consent).where(
                PaymentLabRun.payment_attempt_id == payment_attempt.id,
            ),
        )
        direct_email_eligible = bool(payment_lab_result.scalar_one_or_none())
        if direct_email_eligible:
            payment_link_result = await session.execute(
                select(RecoveryAction.provider_action_url).where(
                    RecoveryAction.recovery_case_id == recovery_case.id,
                    RecoveryAction.action_type == RecoveryActionType.CREATE_PAYMENT_LINK.value,
                    RecoveryAction.provider_action_id == recovery_case.active_payment_link_id,
                ),
            )
            payment_link_url = payment_link_result.scalar_one_or_none()
            direct_email_eligible = payment_link_url is not None

    action.status = RecoveryActionStatus.EXECUTING.value
    action.execution_attempt_count += 1
    action.started_at = executed_at
    action.completed_at = None
    action.last_error = None

    recovery_case.status = RecoveryCaseStatus.EXECUTING.value
    recovery_case.next_action_at = None
    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="action.recovery_message.started",
            actor_type=RecoveryAuditActor.WORKER,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "attempt_number": action.execution_attempt_count,
                "channel": medium.value,
                "provider_action_id": recovery_case.active_payment_link_id,
            },
            occurred_at=executed_at,
        ),
    )

    return RecoveryMessageActionPreparation(
        prepared=PreparedRecoveryMessageAction(
            action_id=action.id,
            recovery_case_id=recovery_case.id,
            provider_payment_id=payment_attempt.provider_payment_id,
            payment_link_id=recovery_case.active_payment_link_id,
            medium=medium,
            attempt_number=action.execution_attempt_count,
            direct_email_eligible=direct_email_eligible,
            payment_link_url=payment_link_url,
            amount_minor=payment_attempt.amount_minor,
            currency=payment_attempt.currency,
        ),
    )


async def complete_recovery_message_action(
    session: AsyncSession,
    *,
    prepared: PreparedRecoveryMessageAction,
    completed_at: datetime,
    provider_action_id: str | None = None,
    provider_action_status: str | None = None,
    audit_actor: RecoveryAuditActor = RecoveryAuditActor.RAZORPAY,
) -> RecoveryActionExecutionResult:
    _require_timezone_aware(completed_at)

    action_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == prepared.action_id,
        )
        .with_for_update(),
    )
    action = action_result.scalar_one_or_none()

    if action is None:
        raise RecoveryActionNotFoundError(
            f"Recovery action {prepared.action_id} does not exist",
        )

    if action.status == RecoveryActionStatus.SUCCEEDED.value:
        return RecoveryActionExecutionResult(
            action_id=action.id,
            recovery_case_id=action.recovery_case_id,
            disposition=RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED,
        )

    if action.status != RecoveryActionStatus.EXECUTING.value:
        raise RecoveryActionNotExecutableError(
            f"Recovery action {action.id} cannot complete from {action.status}",
        )

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == action.recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryActionCaseNotFoundError(
            f"Recovery case {action.recovery_case_id} does not exist",
        )

    action.status = RecoveryActionStatus.SUCCEEDED.value
    action.provider_action_id = provider_action_id or prepared.payment_link_id
    action.provider_action_status = provider_action_status or f"notified_{prepared.medium.value}"
    action.completed_at = completed_at
    action.last_error = None

    recovery_case.last_customer_contact_at = completed_at
    recovery_case.status = RecoveryCaseStatus.WAITING.value
    recovery_case.next_action_at = None
    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="action.recovery_message.succeeded",
            actor_type=audit_actor,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "attempt_number": action.execution_attempt_count,
                "channel": prepared.medium.value,
                "provider_action_id": action.provider_action_id,
                "provider_action_status": action.provider_action_status,
            },
            occurred_at=completed_at,
        ),
    )

    return RecoveryActionExecutionResult(
        action_id=action.id,
        recovery_case_id=recovery_case.id,
        disposition=RecoveryActionExecutionDisposition.SUCCEEDED,
    )


async def fail_recovery_message_action(
    session: AsyncSession,
    *,
    prepared: PreparedRecoveryMessageAction,
    error: RecoveryMessageProviderError,
    failed_at: datetime,
    maximum_attempts: int = DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
) -> bool:
    _require_timezone_aware(failed_at)

    action_result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == prepared.action_id,
        )
        .with_for_update(),
    )
    action = action_result.scalar_one_or_none()

    if action is None:
        raise RecoveryActionNotFoundError(
            f"Recovery action {prepared.action_id} does not exist",
        )

    if action.status != RecoveryActionStatus.EXECUTING.value:
        return False

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == action.recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryActionCaseNotFoundError(
            f"Recovery case {action.recovery_case_id} does not exist",
        )

    retryable = (
        error.retryable
        and not error.delivery_attempted
        and action.execution_attempt_count < maximum_attempts
    )

    action.status = RecoveryActionStatus.FAILED.value
    action.completed_at = failed_at
    action.last_error = (
        f"{type(error).__name__}: "
        f"retryable={str(retryable).lower()} "
        f"delivery_attempted={str(error.delivery_attempted).lower()}"
    )

    if error.status_code is not None:
        action.last_error += f" status_code={error.status_code}"

    if retryable:
        recovery_case.status = RecoveryCaseStatus.READY.value
        recovery_case.next_action_at = failed_at
    else:
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None

    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="action.recovery_message.failed",
            actor_type=RecoveryAuditActor.RAZORPAY,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "attempt_number": action.execution_attempt_count,
                "channel": prepared.medium.value,
                "provider_action_id": prepared.payment_link_id,
                "retryable": retryable,
                "delivery_attempted": error.delivery_attempted,
                "provider_status_code": error.status_code,
                "error_type": type(error).__name__,
            },
            occurred_at=failed_at,
        ),
    )

    return retryable


async def execute_recovery_message_action(
    session_factory: SessionFactory,
    *,
    action_id: UUID,
    customer_provider: RazorpayPaymentCustomerProvider,
    notification_provider: RazorpayPaymentLinkNotificationProvider,
    executed_at: datetime,
    direct_email_provider: ResendRecoveryEmailProvider | None = None,
    direct_email_recipient: str | None = None,
    claim_timeout: timedelta = DEFAULT_ACTION_CLAIM_TIMEOUT,
    maximum_attempts: int = DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
) -> RecoveryActionExecutionResult:
    """Execute one policy-approved recovery notification safely."""
    _require_timezone_aware(executed_at)

    async with session_factory.begin() as prepare_session:
        preparation = await prepare_recovery_message_action(
            prepare_session,
            action_id=action_id,
            executed_at=executed_at,
            claim_timeout=claim_timeout,
            maximum_attempts=maximum_attempts,
        )

    if preparation.terminal_result is not None:
        return preparation.terminal_result

    prepared = preparation.prepared

    if prepared is None:
        raise RuntimeError(
            "Recovery message preparation returned no result",
        )

    try:
        if (
            prepared.direct_email_eligible
            and direct_email_provider is not None
            and direct_email_recipient is not None
            and prepared.payment_link_url is not None
        ):
            result = await direct_email_provider.send_recovery_email(
                recipient=direct_email_recipient,
                payment_link_url=prepared.payment_link_url,
                amount_minor=prepared.amount_minor,
                currency=prepared.currency,
            )
            async with session_factory.begin() as completion_session:
                return await complete_recovery_message_action(
                    completion_session,
                    prepared=prepared,
                    completed_at=executed_at,
                    provider_action_id=result.id,
                    provider_action_status="direct_email_accepted",
                    audit_actor=RecoveryAuditActor.SYSTEM,
                )

        customer = await customer_provider.fetch_payment_customer(
            prepared.provider_payment_id,
        )

        if not _has_contact_for_medium(
            medium=prepared.medium,
            email=customer.email,
            contact=customer.contact,
        ):
            raise RecoveryMessageProviderError(
                "Recovery message contact is unavailable for the selected channel",
                retryable=False,
                delivery_attempted=False,
            )

        await notification_provider.send_notification(
            payment_link_id=prepared.payment_link_id,
            medium=prepared.medium,
        )
    except RazorpayPaymentCustomerProviderError as error:
        provider_error = RecoveryMessageProviderError(
            "Razorpay payment customer lookup failed",
            retryable=error.retryable,
            delivery_attempted=False,
            status_code=error.status_code,
        )
    except RazorpayPaymentLinkNotificationError as error:
        provider_error = RecoveryMessageProviderError(
            "Razorpay payment-link notification failed",
            retryable=False,
            delivery_attempted=True,
            status_code=error.status_code,
        )
    except ResendRecoveryEmailError as error:
        provider_error = RecoveryMessageProviderError(
            "Resend recovery email failed",
            retryable=error.retryable,
            delivery_attempted=True,
            status_code=error.status_code,
        )
    except RecoveryMessageProviderError as error:
        provider_error = error
    else:
        async with session_factory.begin() as completion_session:
            return await complete_recovery_message_action(
                completion_session,
                prepared=prepared,
                completed_at=executed_at,
            )

    async with session_factory.begin() as failure_session:
        retryable = await fail_recovery_message_action(
            failure_session,
            prepared=prepared,
            error=provider_error,
            failed_at=executed_at,
            maximum_attempts=maximum_attempts,
        )

    raise RecoveryMessageProviderFailure(
        "Recovery message execution failed",
        retryable=retryable,
        status_code=provider_error.status_code,
    ) from provider_error
