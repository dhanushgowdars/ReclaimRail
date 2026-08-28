from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryAgentRun,
    RecoveryApproval,
    RecoveryCase,
)
from app.db.models.recovery_outcome import RecoveryOutcome
from app.domain.payments import STOP_RECOVERY_STATES, PaymentState
from app.domain.recovery import RecoveryCaseStatus


class PaymentLabLiveRunNotFoundError(LookupError):
    pass


class PaymentLabLiveStage(StrEnum):
    CHECKOUT = "checkout"
    FAILURE = "failure"
    AGENT = "agent"
    OUTCOME = "outcome"
    COMPLETED = "completed"
    FAILED = "failed"


class PaymentLabLiveStepStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class PaymentLabLiveBusinessState(StrEnum):
    AWAITING_ORIGINAL_PAYMENT = "awaiting_original_payment"
    ORIGINAL_PAYMENT_SUCCEEDED = "original_payment_succeeded"
    FAILURE_STABILIZING = "failure_stabilizing"
    DIAGNOSING = "diagnosing"
    AWAITING_POLICY = "awaiting_policy"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    EXECUTING_ACTION = "executing_action"
    AWAITING_RECOVERY_PAYMENT = "awaiting_recovery_payment"
    RECOVERED = "recovered"
    STOPPING_RECOVERY = "stopping_recovery"
    STOPPED = "stopped"
    ESCALATED = "escalated"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL_OUTCOME_STATUSES = frozenset(
    {
        "recovered",
        "payment_link_expired",
        "payment_link_cancelled",
        "duplicate_collection_prevented",
        "reversed",
    },
)
TERMINAL_CASE_STATUSES = frozenset(
    {
        RecoveryCaseStatus.CANCELLED.value,
        RecoveryCaseStatus.ESCALATED.value,
        RecoveryCaseStatus.EXHAUSTED.value,
    },
)


@dataclass(frozen=True, slots=True)
class PaymentLabLiveStep:
    key: str
    label: str
    status: PaymentLabLiveStepStatus
    occurred_at: datetime | None
    detail: str


@dataclass(frozen=True, slots=True)
class PaymentLabPaymentEvidence:
    payment_attempt_id: UUID
    provider_payment_id: str
    current_state: str
    failure_code: str | None
    failure_reason: str | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentLabAgentEvidence:
    recovery_case_id: UUID
    recovery_case_status: str
    agent_run_id: UUID | None
    agent_run_status: str | None
    planner_provider: str | None
    model_name: str | None
    fallback_used: bool | None
    fallback_reason: str | None
    reasoning_summary: str | None
    proposed_action_count: int
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PaymentLabActionEvidence:
    recovery_action_id: UUID
    sequence_number: int
    action_type: str
    status: str
    policy_outcome: str
    policy_guardrails: tuple[str, ...]
    policy_explanation: str
    provider_action_id: str | None
    provider_action_status: str | None
    provider_action_url: str | None
    provider_action_expires_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PaymentLabApprovalEvidence:
    approval_id: UUID
    recovery_action_id: UUID
    status: str
    request_reason: str
    amount_minor: int
    currency: str
    threshold_minor: int | None
    request_context: dict[str, object]
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    version: int


@dataclass(frozen=True, slots=True)
class PaymentLabOutcomeEvidence:
    recovery_outcome_id: UUID
    status: str
    attribution: str
    gross_recovered_minor: int
    duplicate_collection_prevented_minor: int
    evidence_event_count: int
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentLabLiveRun:
    payment_lab_run_id: UUID
    client_request_id: UUID
    mode: str
    provenance: str
    persisted_status: str
    business_state: PaymentLabLiveBusinessState
    state_label: str
    current_stage: PaymentLabLiveStage
    active_step_key: str | None
    waiting_reason: str | None
    automation_complete: bool
    financial_outcome_terminal: bool
    terminal: bool
    poll_after_milliseconds: int | None
    amount_minor: int
    currency: str
    payment_method: str
    provider_order_id: str | None
    provider_order_status: str | None
    failure_code: str | None
    checkout_expires_at: datetime
    created_at: datetime
    updated_at: datetime
    steps: tuple[PaymentLabLiveStep, ...]
    payment: PaymentLabPaymentEvidence | None
    agent: PaymentLabAgentEvidence | None
    actions: tuple[PaymentLabActionEvidence, ...]
    outcome: PaymentLabOutcomeEvidence | None
    approval: PaymentLabApprovalEvidence | None = None


@dataclass(frozen=True, slots=True)
class _DerivedLiveState:
    business_state: PaymentLabLiveBusinessState
    state_label: str
    current_stage: PaymentLabLiveStage
    active_step_key: str | None
    waiting_reason: str | None
    automation_complete: bool
    financial_outcome_terminal: bool
    terminal: bool


def _fallback_metadata(
    agent_run: RecoveryAgentRun,
) -> tuple[bool | None, str | None]:
    fallback_used = agent_run.evidence.get("fallback_used")
    fallback_reason = agent_run.evidence.get("fallback_reason")
    return (
        fallback_used if isinstance(fallback_used, bool) else None,
        fallback_reason if isinstance(fallback_reason, str) else None,
    )


def _build_payment_evidence(
    payment_attempt: PaymentAttempt | None,
) -> PaymentLabPaymentEvidence | None:
    if payment_attempt is None:
        return None
    return PaymentLabPaymentEvidence(
        payment_attempt_id=payment_attempt.id,
        provider_payment_id=payment_attempt.provider_payment_id,
        current_state=payment_attempt.current_state,
        failure_code=payment_attempt.error_code,
        failure_reason=payment_attempt.error_reason,
        observed_at=payment_attempt.state_event_created_at,
    )


def _build_agent_evidence(
    recovery_case: RecoveryCase | None,
    agent_run: RecoveryAgentRun | None,
) -> PaymentLabAgentEvidence | None:
    if recovery_case is None:
        return None

    fallback_used: bool | None = None
    fallback_reason: str | None = None
    if agent_run is not None:
        fallback_used, fallback_reason = _fallback_metadata(agent_run)

    return PaymentLabAgentEvidence(
        recovery_case_id=recovery_case.id,
        recovery_case_status=recovery_case.status,
        agent_run_id=agent_run.id if agent_run is not None else None,
        agent_run_status=agent_run.status if agent_run is not None else None,
        planner_provider=(agent_run.planner_provider if agent_run is not None else None),
        model_name=agent_run.model_name if agent_run is not None else None,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        reasoning_summary=(agent_run.reasoning_summary if agent_run is not None else None),
        proposed_action_count=(agent_run.proposed_action_count if agent_run is not None else 0),
        completed_at=agent_run.completed_at if agent_run is not None else None,
    )


def _build_action_evidence(
    actions: tuple[RecoveryAction, ...],
) -> tuple[PaymentLabActionEvidence, ...]:
    return tuple(
        PaymentLabActionEvidence(
            recovery_action_id=action.id,
            sequence_number=action.sequence_number,
            action_type=action.action_type,
            status=action.status,
            policy_outcome=action.policy_outcome,
            policy_guardrails=tuple(action.policy_guardrails),
            policy_explanation=action.policy_explanation,
            provider_action_id=action.provider_action_id,
            provider_action_status=action.provider_action_status,
            provider_action_url=action.provider_action_url,
            provider_action_expires_at=action.provider_action_expires_at,
            completed_at=action.completed_at,
        )
        for action in actions
    )


def _build_outcome_evidence(
    outcome: RecoveryOutcome | None,
) -> PaymentLabOutcomeEvidence | None:
    if outcome is None:
        return None
    return PaymentLabOutcomeEvidence(
        recovery_outcome_id=outcome.id,
        status=outcome.status,
        attribution=outcome.attribution,
        gross_recovered_minor=outcome.gross_recovered_minor,
        duplicate_collection_prevented_minor=(outcome.duplicate_collection_prevented_minor),
        evidence_event_count=len(outcome.evidence_event_ids),
        occurred_at=outcome.occurred_at,
    )


def _build_approval_evidence(
    approval: RecoveryApproval | None,
) -> PaymentLabApprovalEvidence | None:
    if approval is None:
        return None
    return PaymentLabApprovalEvidence(
        approval_id=approval.id,
        recovery_action_id=approval.recovery_action_id,
        status=approval.status,
        request_reason=approval.request_reason,
        amount_minor=approval.amount_minor,
        currency=approval.currency,
        threshold_minor=approval.threshold_minor,
        request_context=approval.request_context,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        decided_by=approval.decided_by,
        decision_reason=approval.decision_reason,
        version=approval.version,
    )


def _payment_state(payment_attempt: PaymentAttempt | None) -> PaymentState | None:
    if payment_attempt is None:
        return None
    try:
        return PaymentState(payment_attempt.current_state)
    except ValueError:
        return None


def _derive_live_state(
    run: PaymentLabRun,
    *,
    payment_attempt: PaymentAttempt | None,
    recovery_case: RecoveryCase | None,
    agent_run: RecoveryAgentRun | None,
    actions: tuple[RecoveryAction, ...],
    approval: RecoveryApproval | None,
    outcome: RecoveryOutcome | None,
) -> _DerivedLiveState:
    payment_state = _payment_state(payment_attempt)
    case_status = recovery_case.status if recovery_case is not None else None
    latest_action = actions[-1] if actions else None

    if run.status == PaymentLabRunStatus.PROVIDER_FAILED.value:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.FAILED,
            state_label="Provider run failed safely",
            current_stage=PaymentLabLiveStage.FAILED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )
    if run.status == PaymentLabRunStatus.EXPIRED.value:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.EXPIRED,
            state_label="Checkout expired",
            current_stage=PaymentLabLiveStage.FAILED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )

    if outcome is not None and outcome.status == "recovered":
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.RECOVERED,
            state_label="Provider-confirmed recovery",
            current_stage=PaymentLabLiveStage.COMPLETED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )
    if outcome is not None and outcome.status in TERMINAL_OUTCOME_STATUSES:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.STOPPED,
            state_label="Recovery closed with provider evidence",
            current_stage=PaymentLabLiveStage.COMPLETED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )

    if payment_state in STOP_RECOVERY_STATES:
        if recovery_case is not None and case_status not in TERMINAL_CASE_STATUSES:
            return _DerivedLiveState(
                business_state=PaymentLabLiveBusinessState.STOPPING_RECOVERY,
                state_label="Original payment completed; stopping recovery",
                current_stage=PaymentLabLiveStage.OUTCOME,
                active_step_key="provider_action",
                waiting_reason="Waiting for late-authorization compensation",
                automation_complete=False,
                financial_outcome_terminal=False,
                terminal=False,
            )
        if recovery_case is not None:
            return _DerivedLiveState(
                business_state=PaymentLabLiveBusinessState.STOPPED,
                state_label="Original payment completed; recovery stopped safely",
                current_stage=PaymentLabLiveStage.COMPLETED,
                active_step_key=None,
                waiting_reason=None,
                automation_complete=True,
                financial_outcome_terminal=True,
                terminal=True,
            )
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.ORIGINAL_PAYMENT_SUCCEEDED,
            state_label="Original payment completed; no recovery required",
            current_stage=PaymentLabLiveStage.COMPLETED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )

    if case_status == RecoveryCaseStatus.ESCALATED.value:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.ESCALATED,
            state_label="Automatic recovery escalated safely",
            current_stage=PaymentLabLiveStage.COMPLETED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )
    if case_status in {
        RecoveryCaseStatus.CANCELLED.value,
        RecoveryCaseStatus.EXHAUSTED.value,
    }:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.STOPPED,
            state_label="Recovery stopped safely",
            current_stage=PaymentLabLiveStage.COMPLETED,
            active_step_key=None,
            waiting_reason=None,
            automation_complete=True,
            financial_outcome_terminal=True,
            terminal=True,
        )

    if (
        case_status == RecoveryCaseStatus.AWAITING_APPROVAL.value
        and approval is not None
        and approval.status == "pending"
    ):
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.AWAITING_HUMAN_REVIEW,
            state_label="Operator approval required",
            current_stage=PaymentLabLiveStage.AGENT,
            active_step_key="human_approval",
            waiting_reason="A protected merchant decision is required before execution",
            automation_complete=False,
            financial_outcome_terminal=False,
            terminal=False,
        )

    if outcome is not None or any(action.status == "succeeded" for action in actions):
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.AWAITING_RECOVERY_PAYMENT,
            state_label="Recovery action completed",
            current_stage=PaymentLabLiveStage.OUTCOME,
            active_step_key="measured_outcome",
            waiting_reason="Waiting for provider-confirmed recovery payment",
            automation_complete=True,
            financial_outcome_terminal=False,
            terminal=False,
        )
    if latest_action is not None:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.EXECUTING_ACTION,
            state_label="Bounded provider action in progress",
            current_stage=PaymentLabLiveStage.AGENT,
            active_step_key="provider_action",
            waiting_reason=None,
            automation_complete=False,
            financial_outcome_terminal=False,
            terminal=False,
        )
    if agent_run is not None and agent_run.status == "succeeded":
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.AWAITING_POLICY,
            state_label="Awaiting deterministic policy",
            current_stage=PaymentLabLiveStage.AGENT,
            active_step_key="policy_decision",
            waiting_reason="Waiting for deterministic guardrails",
            automation_complete=False,
            financial_outcome_terminal=False,
            terminal=False,
        )
    if recovery_case is not None or run.status == PaymentLabRunStatus.RECOVERY_RUNNING.value:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.DIAGNOSING,
            state_label="Recovery diagnosis in progress",
            current_stage=PaymentLabLiveStage.AGENT,
            active_step_key="agent_recommendation",
            waiting_reason=None,
            automation_complete=False,
            financial_outcome_terminal=False,
            terminal=False,
        )
    if payment_state is PaymentState.FAILED:
        return _DerivedLiveState(
            business_state=PaymentLabLiveBusinessState.FAILURE_STABILIZING,
            state_label="Failure verified; safety stabilization active",
            current_stage=PaymentLabLiveStage.FAILURE,
            active_step_key="recovery_case",
            waiting_reason="Five-second late-authorization safety window",
            automation_complete=False,
            financial_outcome_terminal=False,
            terminal=False,
        )
    return _DerivedLiveState(
        business_state=PaymentLabLiveBusinessState.AWAITING_ORIGINAL_PAYMENT,
        state_label="Waiting for provider payment result",
        current_stage=PaymentLabLiveStage.CHECKOUT,
        active_step_key="verified_failure",
        waiting_reason="Waiting for signed provider evidence",
        automation_complete=False,
        financial_outcome_terminal=False,
        terminal=False,
    )


def _build_steps(
    run: PaymentLabRun,
    *,
    derived_state: _DerivedLiveState,
    payment_attempt: PaymentAttempt | None,
    recovery_case: RecoveryCase | None,
    agent_run: RecoveryAgentRun | None,
    actions: tuple[RecoveryAction, ...],
    approval: RecoveryApproval | None,
    outcome: RecoveryOutcome | None,
) -> tuple[PaymentLabLiveStep, ...]:
    payment_state = _payment_state(payment_attempt)
    if derived_state.business_state is PaymentLabLiveBusinessState.ORIGINAL_PAYMENT_SUCCEEDED:
        return (
            PaymentLabLiveStep(
                key="payment_attempt",
                label="Original payment",
                status=PaymentLabLiveStepStatus.COMPLETED,
                occurred_at=(
                    payment_attempt.state_event_created_at
                    if payment_attempt is not None
                    else run.updated_at
                ),
                detail="Provider-confirmed payment succeeded; recovery was not required",
            ),
        )

    provider_failed = run.status == PaymentLabRunStatus.PROVIDER_FAILED.value
    run_expired = run.status == PaymentLabRunStatus.EXPIRED.value
    checkout_status = (
        PaymentLabLiveStepStatus.COMPLETED
        if run.provider_order_id is not None
        else PaymentLabLiveStepStatus.ACTIVE
    )

    failure_observed = payment_state is PaymentState.FAILED or recovery_case is not None
    failure_status = PaymentLabLiveStepStatus.PENDING
    if failure_observed:
        failure_status = PaymentLabLiveStepStatus.COMPLETED
    elif provider_failed or run_expired:
        failure_status = PaymentLabLiveStepStatus.FAILED
    elif run.status in {
        PaymentLabRunStatus.CHECKOUT_READY.value,
        PaymentLabRunStatus.COMPLETED.value,
    }:
        failure_status = PaymentLabLiveStepStatus.ACTIVE

    case_status = PaymentLabLiveStepStatus.PENDING
    if recovery_case is not None:
        case_status = PaymentLabLiveStepStatus.COMPLETED
    elif payment_state is PaymentState.FAILED:
        case_status = PaymentLabLiveStepStatus.ACTIVE

    agent_status = PaymentLabLiveStepStatus.PENDING
    if agent_run is not None and agent_run.status == "succeeded":
        agent_status = PaymentLabLiveStepStatus.COMPLETED
    elif agent_run is not None and agent_run.status == "failed":
        agent_status = PaymentLabLiveStepStatus.FAILED
    elif recovery_case is not None:
        agent_status = PaymentLabLiveStepStatus.ACTIVE

    latest_action = actions[-1] if actions else None
    policy_status = PaymentLabLiveStepStatus.PENDING
    if latest_action is not None:
        policy_status = PaymentLabLiveStepStatus.COMPLETED
    elif agent_run is not None and agent_run.status == "succeeded":
        policy_status = PaymentLabLiveStepStatus.ACTIVE

    approval_stopped_execution = approval is not None and approval.status in {
        "rejected",
        "expired",
    }
    provider_status = PaymentLabLiveStepStatus.PENDING
    if derived_state.business_state is PaymentLabLiveBusinessState.STOPPING_RECOVERY:
        provider_status = PaymentLabLiveStepStatus.ACTIVE
    elif approval_stopped_execution:
        provider_status = PaymentLabLiveStepStatus.COMPLETED
    elif latest_action is not None:
        if latest_action.status == "succeeded":
            provider_status = PaymentLabLiveStepStatus.COMPLETED
        elif latest_action.status == "failed":
            provider_status = PaymentLabLiveStepStatus.FAILED
        elif latest_action.status == "approval_required":
            provider_status = PaymentLabLiveStepStatus.PENDING
        elif latest_action.policy_outcome in {"block", "escalate", "stop"}:
            provider_status = PaymentLabLiveStepStatus.COMPLETED
        else:
            provider_status = PaymentLabLiveStepStatus.ACTIVE

    approval_status = PaymentLabLiveStepStatus.PENDING
    approval_detail = "No human approval required"
    approval_occurred_at: datetime | None = None
    if approval is not None:
        approval_occurred_at = approval.decided_at or approval.requested_at
        approval_detail = {
            "pending": "Waiting for a protected merchant decision",
            "approved": "Merchant approved the bounded action",
            "rejected": "Merchant rejected the bounded action",
            "expired": "Approval window expired without execution",
        }.get(approval.status, "Approval state is unavailable")
        approval_status = (
            PaymentLabLiveStepStatus.ACTIVE
            if approval.status == "pending"
            else PaymentLabLiveStepStatus.COMPLETED
        )
    elif latest_action is not None:
        approval_status = PaymentLabLiveStepStatus.COMPLETED

    successful_actions = tuple(action for action in actions if action.status == "succeeded")
    safe_disposition = (
        recovery_case.status
        if recovery_case is not None and recovery_case.status in TERMINAL_CASE_STATUSES
        else None
    )
    outcome_status = PaymentLabLiveStepStatus.PENDING
    if (
        outcome is not None and outcome.status in TERMINAL_OUTCOME_STATUSES
    ) or safe_disposition is not None:
        outcome_status = PaymentLabLiveStepStatus.COMPLETED
    elif outcome is not None or successful_actions:
        outcome_status = PaymentLabLiveStepStatus.ACTIVE
    elif provider_failed or run_expired:
        outcome_status = PaymentLabLiveStepStatus.FAILED

    return (
        PaymentLabLiveStep(
            key="payment_attempt",
            label="Payment attempt",
            status=checkout_status,
            occurred_at=run.provider_created_at or run.created_at,
            detail="Razorpay Test Mode order created",
        ),
        PaymentLabLiveStep(
            key="verified_failure",
            label="Verified failure" if failure_observed else "Provider result",
            status=failure_status,
            occurred_at=(
                payment_attempt.state_event_created_at
                if payment_state is PaymentState.FAILED and payment_attempt is not None
                else recovery_case.opened_at
                if recovery_case is not None
                else None
            ),
            detail=(
                "Signed provider evidence linked"
                if failure_observed
                else "Waiting for signed provider evidence"
            ),
        ),
        PaymentLabLiveStep(
            key="recovery_case",
            label="Recovery case opened",
            status=case_status,
            occurred_at=(recovery_case.opened_at if recovery_case is not None else None),
            detail=(
                "Failure promoted into a bounded recovery case"
                if recovery_case is not None
                else "Five-second signed-evidence stabilization window before recovery begins"
            ),
        ),
        PaymentLabLiveStep(
            key="agent_recommendation",
            label="Agent recommendation",
            status=agent_status,
            occurred_at=(
                agent_run.completed_at or agent_run.started_at if agent_run is not None else None
            ),
            detail=(
                "Gemini proposal persisted with decision evidence"
                if agent_status is PaymentLabLiveStepStatus.COMPLETED
                else "Gemini is preparing a bounded proposal"
            ),
        ),
        PaymentLabLiveStep(
            key="policy_decision",
            label="Policy decision",
            status=policy_status,
            occurred_at=(latest_action.policy_evaluated_at if latest_action is not None else None),
            detail=(
                f"Deterministic policy: {latest_action.policy_outcome}"
                if latest_action is not None
                else "Waiting for deterministic guardrails"
            ),
        ),
        PaymentLabLiveStep(
            key="human_approval",
            label="Human approval",
            status=approval_status,
            occurred_at=approval_occurred_at,
            detail=approval_detail,
        ),
        PaymentLabLiveStep(
            key="provider_action",
            label=(
                "Safe disposition"
                if approval_stopped_execution
                or (
                    latest_action is not None
                    and latest_action.policy_outcome in {"block", "escalate", "stop"}
                )
                else "Provider action"
            ),
            status=provider_status,
            occurred_at=(
                latest_action.completed_at or latest_action.started_at or latest_action.created_at
                if latest_action is not None
                else None
            ),
            detail=(
                "Stopping active recovery after original-payment completion"
                if derived_state.business_state is PaymentLabLiveBusinessState.STOPPING_RECOVERY
                else "Approval closed without provider execution"
                if approval_stopped_execution
                else "Razorpay payment link created"
                if latest_action is not None and latest_action.provider_action_id is not None
                else "Policy stopped money-facing execution"
                if latest_action is not None
                and latest_action.policy_outcome in {"block", "escalate", "stop"}
                else "Waiting for idempotent provider execution"
            ),
        ),
        PaymentLabLiveStep(
            key="measured_outcome",
            label="Measured outcome",
            status=outcome_status,
            occurred_at=(
                outcome.occurred_at
                if outcome is not None
                else (
                    actions[-1].completed_at
                    if safe_disposition is not None and actions
                    else (
                        agent_run.completed_at
                        if safe_disposition is not None and agent_run is not None
                        else (successful_actions[-1].completed_at if successful_actions else None)
                    )
                )
            ),
            detail=(
                "Evidence-backed outcome recorded"
                if outcome is not None and outcome_status is PaymentLabLiveStepStatus.COMPLETED
                else "Waiting for late-authorization compensation"
                if derived_state.business_state is PaymentLabLiveBusinessState.STOPPING_RECOVERY
                else (
                    "Policy required human review; no financial action executed"
                    if safe_disposition == RecoveryCaseStatus.ESCALATED.value
                    else "Recovery stopped safely; no financial result was invented"
                )
                if safe_disposition is not None
                else "Waiting for provider reconciliation"
            ),
        ),
    )


async def load_payment_lab_live_run(
    session: AsyncSession,
    *,
    payment_lab_run_id: UUID,
) -> PaymentLabLiveRun:
    run = await session.get(PaymentLabRun, payment_lab_run_id)
    if run is None:
        raise PaymentLabLiveRunNotFoundError(
            f"Payment Lab run {payment_lab_run_id} does not exist",
        )

    payment_attempt = (
        await session.get(PaymentAttempt, run.payment_attempt_id)
        if run.payment_attempt_id is not None
        else None
    )
    recovery_case: RecoveryCase | None = None
    agent_run: RecoveryAgentRun | None = None
    actions: tuple[RecoveryAction, ...] = ()
    outcome: RecoveryOutcome | None = None
    approval: RecoveryApproval | None = None

    if run.payment_attempt_id is not None:
        case_result = await session.execute(
            select(RecoveryCase).where(
                RecoveryCase.payment_attempt_id == run.payment_attempt_id,
            ),
        )
        recovery_case = case_result.scalar_one_or_none()

    if recovery_case is not None:
        agent_result = await session.execute(
            select(RecoveryAgentRun)
            .where(RecoveryAgentRun.recovery_case_id == recovery_case.id)
            .order_by(RecoveryAgentRun.run_number.desc())
            .limit(1),
        )
        agent_run = agent_result.scalar_one_or_none()

        action_result = await session.execute(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == recovery_case.id)
            .order_by(RecoveryAction.sequence_number),
        )
        actions = tuple(action_result.scalars().all())

        approval_result = await session.execute(
            select(RecoveryApproval)
            .where(RecoveryApproval.recovery_case_id == recovery_case.id)
            .order_by(RecoveryApproval.requested_at.desc())
            .limit(1),
        )
        approval = approval_result.scalar_one_or_none()

        outcome_result = await session.execute(
            select(RecoveryOutcome).where(
                RecoveryOutcome.recovery_case_id == recovery_case.id,
            ),
        )
        outcome = outcome_result.scalar_one_or_none()

    derived_state = _derive_live_state(
        run,
        payment_attempt=payment_attempt,
        recovery_case=recovery_case,
        agent_run=agent_run,
        actions=actions,
        approval=approval,
        outcome=outcome,
    )
    return PaymentLabLiveRun(
        payment_lab_run_id=run.id,
        client_request_id=run.client_request_id,
        mode=run.mode,
        provenance=run.provenance,
        persisted_status=run.status,
        business_state=derived_state.business_state,
        state_label=derived_state.state_label,
        current_stage=derived_state.current_stage,
        active_step_key=derived_state.active_step_key,
        waiting_reason=derived_state.waiting_reason,
        automation_complete=derived_state.automation_complete,
        financial_outcome_terminal=(derived_state.financial_outcome_terminal),
        terminal=derived_state.terminal,
        poll_after_milliseconds=None if derived_state.terminal else 500,
        amount_minor=run.amount_minor,
        currency=run.currency,
        payment_method=(
            payment_attempt.method
            if payment_attempt is not None and payment_attempt.method is not None
            else run.payment_method
        ),
        provider_order_id=run.provider_order_id,
        provider_order_status=run.provider_order_status,
        failure_code=run.failure_code,
        checkout_expires_at=run.checkout_expires_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=_build_steps(
            run,
            derived_state=derived_state,
            payment_attempt=payment_attempt,
            recovery_case=recovery_case,
            agent_run=agent_run,
            actions=actions,
            approval=approval,
            outcome=outcome,
        ),
        payment=_build_payment_evidence(payment_attempt),
        agent=_build_agent_evidence(recovery_case, agent_run),
        actions=_build_action_evidence(actions),
        approval=_build_approval_evidence(approval),
        outcome=_build_outcome_evidence(outcome),
    )
