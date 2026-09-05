from dataclasses import dataclass, replace
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
from app.domain.incidents import IncidentSeverity
from app.domain.payments import PaymentState
from app.domain.recovery import (
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPolicyOutcome,
    build_recovery_policy_checks,
    evaluate_recovery_proposal,
)
from app.integrations.razorpay.payment_customers import (
    RazorpayPaymentCustomerProvider,
    RazorpayPaymentCustomerProviderError,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkRequest,
)
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)
from app.services.recovery_incident_context import (
    ActiveRecoveryIncidentContext,
    load_active_recovery_incident_context,
)

SessionFactory = async_sessionmaker[AsyncSession]

DEFAULT_ACTION_CLAIM_TIMEOUT = timedelta(minutes=2)
DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS = 3
DEFAULT_PAYMENT_LINK_LIFETIME = timedelta(hours=24)
DEFAULT_PROVIDER_RETRY_DELAY = timedelta(seconds=30)
DEFAULT_RATE_LIMIT_RETRY_DELAY = timedelta(minutes=5)


class RecoveryActionExecutionDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    ALREADY_SUCCEEDED = "already_succeeded"
    POLICY_BLOCKED = "policy_blocked"
    POLICY_ESCALATED = "policy_escalated"
    POLICY_STOPPED = "policy_stopped"


class RecoveryActionNotFoundError(LookupError):
    pass


class RecoveryActionCaseNotFoundError(LookupError):
    pass


class RecoveryActionPaymentNotFoundError(LookupError):
    pass


class RecoveryActionNotExecutableError(ValueError):
    pass


class RecoveryActionNotDueError(ValueError):
    pass


class RecoveryActionInProgressError(RuntimeError):
    pass


class RecoveryActionProviderFailure(RuntimeError):
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
class PreparedPaymentLinkAction:
    action_id: UUID
    recovery_case_id: UUID
    provider_payment_id: str
    customer_contact_allowed: bool
    attempt_number: int
    reference_id: str
    request: RazorpayPaymentLinkRequest


@dataclass(frozen=True, slots=True)
class RecoveryActionExecutionResult:
    action_id: UUID
    recovery_case_id: UUID
    disposition: RecoveryActionExecutionDisposition
    payment_link: RazorpayPaymentLink | None = None
    recovered_existing_link: bool = False


@dataclass(frozen=True, slots=True)
class RecoveryActionPreparation:
    prepared: PreparedPaymentLinkAction | None = None
    terminal_result: RecoveryActionExecutionResult | None = None

    def __post_init__(self) -> None:
        if (self.prepared is None) == (self.terminal_result is None):
            raise ValueError(
                "Action preparation requires exactly one result",
            )


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Recovery action execution time must be timezone-aware",
        )


def build_payment_link_reference_id(action_id: UUID) -> str:
    """Build a stable Razorpay reference within the provider's 40-char limit."""
    return f"rr_{action_id.hex}"


def _build_proposal(
    action: RecoveryAction,
) -> RecoveryActionProposal:
    return RecoveryActionProposal(
        action_type=RecoveryActionType(action.action_type),
        reason=action.proposal_reason,
        amount_minor=action.amount_minor,
        currency=action.currency,
        channel=(RecoveryChannel(action.channel) if action.channel is not None else None),
        target_payment_method=action.target_payment_method,
        execute_after=action.execute_after,
    )


def _build_case_snapshot(
    recovery_case: RecoveryCase,
    payment_attempt: PaymentAttempt,
    *,
    incident_severity: IncidentSeverity | None,
) -> RecoveryCaseSnapshot:
    return RecoveryCaseSnapshot(
        case_id=recovery_case.id,
        payment_attempt_id=recovery_case.payment_attempt_id,
        provider_payment_id=payment_attempt.provider_payment_id,
        payment_state=PaymentState(payment_attempt.current_state),
        amount_minor=recovery_case.amount_minor,
        currency=recovery_case.currency,
        payment_method=recovery_case.payment_method,
        status=RecoveryCaseStatus(recovery_case.status),
        recovery_attempt_count=recovery_case.recovery_attempt_count,
        customer_contact_allowed=recovery_case.customer_contact_allowed,
        last_customer_contact_at=recovery_case.last_customer_contact_at,
        active_payment_link_id=recovery_case.active_payment_link_id,
        active_incident_severity=incident_severity,
        late_authorization_detected_at=(
            payment_attempt.late_authorization_detected_at
            or recovery_case.late_authorization_detected_at
        ),
        recovered_at=recovery_case.recovered_at,
    )


async def _load_active_incident_context(
    session: AsyncSession,
    *,
    recovery_case: RecoveryCase,
) -> ActiveRecoveryIncidentContext | None:
    return await load_active_recovery_incident_context(
        session,
        source_incident_id=recovery_case.source_incident_id,
        currency=recovery_case.currency,
        payment_method=recovery_case.payment_method,
    )


def _policy_status(
    outcome: RecoveryPolicyOutcome,
) -> RecoveryActionStatus:
    return {
        RecoveryPolicyOutcome.BLOCK: RecoveryActionStatus.BLOCKED,
        RecoveryPolicyOutcome.ESCALATE: (RecoveryActionStatus.ESCALATED),
        RecoveryPolicyOutcome.STOP: RecoveryActionStatus.STOPPED,
    }[outcome]


def _policy_disposition(
    outcome: RecoveryPolicyOutcome,
) -> RecoveryActionExecutionDisposition:
    return {
        RecoveryPolicyOutcome.BLOCK: (RecoveryActionExecutionDisposition.POLICY_BLOCKED),
        RecoveryPolicyOutcome.ESCALATE: (RecoveryActionExecutionDisposition.POLICY_ESCALATED),
        RecoveryPolicyOutcome.STOP: (RecoveryActionExecutionDisposition.POLICY_STOPPED),
    }[outcome]


def _apply_denied_case_projection(
    recovery_case: RecoveryCase,
    *,
    outcome: RecoveryPolicyOutcome,
    executed_at: datetime,
) -> None:
    if outcome is RecoveryPolicyOutcome.STOP:
        recovery_case.status = RecoveryCaseStatus.CANCELLED.value
        recovery_case.next_action_at = None
        recovery_case.closed_at = executed_at
        recovery_case.close_reason = "execution_policy_stop"
    elif outcome is RecoveryPolicyOutcome.ESCALATE:
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None
    else:
        recovery_case.status = RecoveryCaseStatus.WAITING.value
        recovery_case.next_action_at = None

    recovery_case.version += 1


async def prepare_recovery_payment_link_action(
    session: AsyncSession,
    *,
    action_id: UUID,
    executed_at: datetime,
    claim_timeout: timedelta = DEFAULT_ACTION_CLAIM_TIMEOUT,
    maximum_attempts: int = DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
    payment_link_lifetime: timedelta = DEFAULT_PAYMENT_LINK_LIFETIME,
) -> RecoveryActionPreparation:
    """Lock, re-evaluate and claim one payment-link action."""
    _require_timezone_aware(executed_at)

    if claim_timeout <= timedelta(0):
        raise ValueError(
            "Action claim timeout must be positive",
        )

    if maximum_attempts < 1:
        raise ValueError(
            "Maximum execution attempts must be positive",
        )
    if payment_link_lifetime <= timedelta(0):
        raise ValueError("Payment-link lifetime must be positive")

    action_result = await session.execute(
        select(RecoveryAction).where(RecoveryAction.id == action_id).with_for_update(),
    )
    action = action_result.scalar_one_or_none()

    if action is None:
        raise RecoveryActionNotFoundError(
            f"Recovery action {action_id} does not exist",
        )

    if action.action_type != RecoveryActionType.CREATE_PAYMENT_LINK.value:
        raise RecoveryActionNotExecutableError(
            f"Recovery action {action_id} is not a payment-link action",
        )

    if action.status == RecoveryActionStatus.SUCCEEDED.value:
        return RecoveryActionPreparation(
            terminal_result=RecoveryActionExecutionResult(
                action_id=action.id,
                recovery_case_id=action.recovery_case_id,
                disposition=(RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED),
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

    incident_context = await _load_active_incident_context(
        session,
        recovery_case=recovery_case,
    )

    snapshot = _build_case_snapshot(
        recovery_case,
        payment_attempt,
        incident_severity=(incident_context.severity if incident_context is not None else None),
    )
    proposal = _build_proposal(action)

    decision = evaluate_recovery_proposal(snapshot, proposal, evaluated_at=executed_at)

    action.policy_outcome = decision.outcome.value
    action.policy_guardrails = [guardrail.value for guardrail in decision.guardrails]
    approval_checks = [
        check
        for check in (action.policy_check_results or [])
        if check.get("code") == "human_approval_boundary"
    ]
    action.policy_check_results = [
        check.as_dict()
        for check in build_recovery_policy_checks(
            snapshot,
            proposal,
            evaluated_at=executed_at,
        )
    ] + approval_checks
    action.policy_check_results = [
        check
        for check in action.policy_check_results
        if check.get("code") != "payment_link_expiry_window"
    ]
    action.policy_check_results.append(
        {
            "code": "payment_link_expiry_window",
            "label": "Recovery payment-link expiry",
            "actual_value": (
                f"{int(payment_link_lifetime.total_seconds() // 3600)} hours; "
                f"expires {(executed_at + payment_link_lifetime).isoformat()}"
            ),
            "rule": "Recovery payment links use the configured bounded expiry window",
            "result": "passed",
        },
    )
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
                    "policy_outcome": (decision.outcome.value),
                    "guardrails": [guardrail.value for guardrail in decision.guardrails],
                    "policy_check_results": action.policy_check_results,
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

        return RecoveryActionPreparation(
            terminal_result=RecoveryActionExecutionResult(
                action_id=action.id,
                recovery_case_id=recovery_case.id,
                disposition=_policy_disposition(
                    decision.outcome,
                ),
            ),
        )

    action.status = RecoveryActionStatus.EXECUTING.value
    action.execution_attempt_count += 1
    action.started_at = executed_at
    action.completed_at = None
    action.last_error = None

    recovery_case.status = RecoveryCaseStatus.EXECUTING.value
    recovery_case.next_action_at = None
    recovery_case.version += 1

    if action.amount_minor is None or action.currency is None:
        raise RecoveryActionNotExecutableError(
            f"Recovery action {action.id} has an invalid payment-link shape",
        )

    reference_id = build_payment_link_reference_id(
        action.id,
    )

    request = RazorpayPaymentLinkRequest(
        amount_minor=action.amount_minor,
        currency=action.currency,
        reference_id=reference_id,
        description=(f"ReclaimRail recovery for payment {payment_attempt.provider_payment_id}"),
        expire_by=executed_at + payment_link_lifetime,
        notes={
            "recovery_case_id": str(recovery_case.id),
            "recovery_action_id": str(action.id),
        },
    )

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="action.payment_link.started",
            actor_type=RecoveryAuditActor.WORKER,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "attempt_number": (action.execution_attempt_count),
                "reference_id": reference_id,
                "amount_minor": request.amount_minor,
                "currency": request.currency,
            },
            occurred_at=executed_at,
        ),
    )

    return RecoveryActionPreparation(
        prepared=PreparedPaymentLinkAction(
            action_id=action.id,
            recovery_case_id=recovery_case.id,
            provider_payment_id=(payment_attempt.provider_payment_id),
            customer_contact_allowed=recovery_case.customer_contact_allowed,
            attempt_number=(action.execution_attempt_count),
            reference_id=reference_id,
            request=request,
        ),
    )


def _validate_provider_link(
    prepared: PreparedPaymentLinkAction,
    payment_link: RazorpayPaymentLink,
) -> None:
    if payment_link.reference_id != prepared.reference_id:
        raise RazorpayPaymentLinkProviderError(
            "Razorpay Payment Link reference did not match the recovery action",
            retryable=False,
        )

    if payment_link.amount_minor != prepared.request.amount_minor:
        raise RazorpayPaymentLinkProviderError(
            "Razorpay Payment Link amount did not match the recovery action",
            retryable=False,
        )

    if payment_link.currency != prepared.request.currency:
        raise RazorpayPaymentLinkProviderError(
            "Razorpay Payment Link currency did not match the recovery action",
            retryable=False,
        )


async def complete_recovery_payment_link_action(
    session: AsyncSession,
    *,
    prepared: PreparedPaymentLinkAction,
    payment_link: RazorpayPaymentLink,
    recovered_existing_link: bool,
    completed_at: datetime,
) -> RecoveryActionExecutionResult:
    _require_timezone_aware(completed_at)
    _validate_provider_link(
        prepared,
        payment_link,
    )

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
            disposition=(RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED),
            payment_link=payment_link,
            recovered_existing_link=recovered_existing_link,
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
    action.provider_action_id = payment_link.payment_link_id
    action.provider_action_status = payment_link.status.value
    action.provider_action_url = payment_link.short_url
    action.provider_action_expires_at = (
        payment_link.provider_expires_at or prepared.request.expire_by
    )
    action.completed_at = completed_at
    action.last_error = None

    recovery_case.active_payment_link_id = payment_link.payment_link_id
    recovery_case.recovery_attempt_count += 1
    recovery_case.status = RecoveryCaseStatus.READY.value
    recovery_case.next_action_at = completed_at
    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="action.payment_link.succeeded",
            actor_type=RecoveryAuditActor.RAZORPAY,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "attempt_number": (action.execution_attempt_count),
                "provider_action_id": (payment_link.payment_link_id),
                "provider_action_status": (payment_link.status.value),
                "provider_action_expires_at": (
                    action.provider_action_expires_at.isoformat()
                    if action.provider_action_expires_at is not None
                    else None
                ),
                "reference_id": (payment_link.reference_id),
                "recovered_existing_link": (recovered_existing_link),
            },
            occurred_at=completed_at,
        ),
    )

    return RecoveryActionExecutionResult(
        action_id=action.id,
        recovery_case_id=recovery_case.id,
        disposition=(RecoveryActionExecutionDisposition.SUCCEEDED),
        payment_link=payment_link,
        recovered_existing_link=recovered_existing_link,
    )


async def fail_recovery_payment_link_action(
    session: AsyncSession,
    *,
    prepared: PreparedPaymentLinkAction,
    error: RazorpayPaymentLinkProviderError,
    failed_at: datetime,
    maximum_attempts: int = (DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS),
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

    rate_limited = error.status_code == 429
    # A provider throttle is not a failed recovery decision.  Do not consume the
    # final bounded attempt just because Razorpay asks us to slow down.
    retryable = error.retryable and (
        rate_limited or action.execution_attempt_count < maximum_attempts
    )

    action.status = RecoveryActionStatus.FAILED.value
    action.completed_at = failed_at
    action.last_error = (
        f"{type(error).__name__}: retryable={str(retryable).lower()}"
        + (f" status_code={error.status_code}" if error.status_code is not None else "")
        + (
            f" provider_code={error.provider_error_code}"
            if error.provider_error_code is not None
            else ""
        )
    )

    if retryable:
        recovery_case.status = RecoveryCaseStatus.READY.value
        retry_delay = (
            DEFAULT_RATE_LIMIT_RETRY_DELAY
            if rate_limited
            else DEFAULT_PROVIDER_RETRY_DELAY * (2 ** (action.execution_attempt_count - 1))
        )
        action.execute_after = failed_at + retry_delay
        recovery_case.next_action_at = action.execute_after
    else:
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None

    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="action.payment_link.failed",
            actor_type=RecoveryAuditActor.RAZORPAY,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "attempt_number": (action.execution_attempt_count),
                "retryable": retryable,
                "provider_status_code": (error.status_code),
                "provider_error_code": (error.provider_error_code),
                "rate_limited": rate_limited,
                "error_type": type(error).__name__,
            },
            occurred_at=failed_at,
        ),
    )

    return retryable


async def attach_transient_customer_to_payment_link_request(
    prepared: PreparedPaymentLinkAction,
    *,
    customer_provider: RazorpayPaymentCustomerProvider | None,
) -> PreparedPaymentLinkAction:
    """Attach transient Razorpay contact data without persisting it locally."""

    if not prepared.customer_contact_allowed or customer_provider is None:
        return prepared

    try:
        customer = await customer_provider.fetch_payment_customer(
            prepared.provider_payment_id,
        )
    except RazorpayPaymentCustomerProviderError:
        # Contact lookup is optional enrichment for an unshared recovery link.
        # A failed/declined original payment may not have a retrievable customer
        # record, but that must never prevent the already-approved link itself.
        return prepared

    if customer.email is None and customer.contact is None:
        return prepared

    request = prepared.request.model_copy(
        update={
            "customer_email": customer.email,
            "customer_contact": customer.contact,
            "notify_email": False,
            "notify_sms": False,
        },
    )

    return replace(
        prepared,
        request=request,
    )


async def execute_recovery_payment_link_action(
    session_factory: SessionFactory,
    *,
    action_id: UUID,
    provider: RazorpayPaymentLinkProvider,
    customer_provider: RazorpayPaymentCustomerProvider | None = None,
    executed_at: datetime,
    claim_timeout: timedelta = DEFAULT_ACTION_CLAIM_TIMEOUT,
    maximum_attempts: int = (DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS),
    payment_link_lifetime: timedelta = DEFAULT_PAYMENT_LINK_LIFETIME,
) -> RecoveryActionExecutionResult:
    """Execute an approved action with provider idempotency."""
    _require_timezone_aware(executed_at)

    async with session_factory.begin() as prepare_session:
        preparation = await prepare_recovery_payment_link_action(
            prepare_session,
            action_id=action_id,
            executed_at=executed_at,
            claim_timeout=claim_timeout,
            maximum_attempts=maximum_attempts,
            payment_link_lifetime=payment_link_lifetime,
        )

    if preparation.terminal_result is not None:
        return preparation.terminal_result

    prepared = preparation.prepared

    if prepared is None:
        raise RuntimeError(
            "Payment-link action preparation returned no result",
        )

    try:
        prepared = await attach_transient_customer_to_payment_link_request(
            prepared,
            customer_provider=customer_provider,
        )

        # A first execution owns a fresh, deterministic reference ID.  Creating
        # directly avoids spending a Razorpay request on a list/search endpoint
        # before the real action.  Retry attempts still recover any existing
        # link by that same reference before creating another one.
        if prepared.attempt_number == 1:
            payment_link = await provider.create_payment_link(
                prepared.request,
            )
            recovered_existing_link = False
        else:
            payment_link = await provider.find_payment_link_by_reference(
                prepared.reference_id,
            )
            recovered_existing_link = payment_link is not None

            if payment_link is None:
                payment_link = await provider.create_payment_link(
                    prepared.request,
                )

        _validate_provider_link(
            prepared,
            payment_link,
        )
    except RazorpayPaymentLinkProviderError as error:
        async with session_factory.begin() as failure_session:
            retryable = await fail_recovery_payment_link_action(
                failure_session,
                prepared=prepared,
                error=error,
                failed_at=executed_at,
                maximum_attempts=maximum_attempts,
            )

        raise RecoveryActionProviderFailure(
            "Razorpay payment-link execution failed",
            retryable=retryable,
            status_code=error.status_code,
        ) from error

    async with session_factory.begin() as completion_session:
        return await complete_recovery_payment_link_action(
            completion_session,
            prepared=prepared,
            payment_link=payment_link,
            recovered_existing_link=(recovered_existing_link),
            completed_at=executed_at,
        )
