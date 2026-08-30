from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import RecoveryAction, RecoveryAgentRun, RecoveryCase
from app.db.models.recovery_outcome import RecoveryOutcome
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


TERMINAL_OUTCOME_STATUSES = frozenset(
    {
        "recovered",
        "payment_link_expired",
        "payment_link_cancelled",
        "duplicate_collection_prevented",
        "reversed",
    },
)
TERMINAL_RUN_STATUSES = frozenset(
    {
        PaymentLabRunStatus.COMPLETED.value,
        PaymentLabRunStatus.PROVIDER_FAILED.value,
        PaymentLabRunStatus.EXPIRED.value,
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
    current_stage: PaymentLabLiveStage
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


def _derive_terminal(
    run: PaymentLabRun,
    recovery_case: RecoveryCase | None,
    outcome: RecoveryOutcome | None,
) -> bool:
    return (
        run.status in TERMINAL_RUN_STATUSES
        or (recovery_case is not None and recovery_case.status in TERMINAL_CASE_STATUSES)
        or (outcome is not None and outcome.status in TERMINAL_OUTCOME_STATUSES)
    )


def _derive_stage(
    run: PaymentLabRun,
    *,
    payment_attempt: PaymentAttempt | None,
    recovery_case: RecoveryCase | None,
    agent_run: RecoveryAgentRun | None,
    actions: tuple[RecoveryAction, ...],
    outcome: RecoveryOutcome | None,
) -> PaymentLabLiveStage:
    if run.status in {
        PaymentLabRunStatus.PROVIDER_FAILED.value,
        PaymentLabRunStatus.EXPIRED.value,
    }:
        return PaymentLabLiveStage.FAILED
    if outcome is not None and outcome.status in TERMINAL_OUTCOME_STATUSES:
        return PaymentLabLiveStage.COMPLETED
    if recovery_case is not None and recovery_case.status in TERMINAL_CASE_STATUSES:
        return PaymentLabLiveStage.COMPLETED
    if outcome is not None or any(action.status == "succeeded" for action in actions):
        return PaymentLabLiveStage.OUTCOME
    if agent_run is not None or run.status == PaymentLabRunStatus.RECOVERY_RUNNING.value:
        return PaymentLabLiveStage.AGENT
    if payment_attempt is not None:
        return PaymentLabLiveStage.FAILURE
    return PaymentLabLiveStage.CHECKOUT


def _build_steps(
    run: PaymentLabRun,
    *,
    payment_attempt: PaymentAttempt | None,
    recovery_case: RecoveryCase | None,
    agent_run: RecoveryAgentRun | None,
    actions: tuple[RecoveryAction, ...],
    outcome: RecoveryOutcome | None,
) -> tuple[PaymentLabLiveStep, ...]:
    provider_failed = run.status == PaymentLabRunStatus.PROVIDER_FAILED.value
    run_expired = run.status == PaymentLabRunStatus.EXPIRED.value
    checkout_status = (
        PaymentLabLiveStepStatus.COMPLETED
        if run.provider_order_id is not None
        else PaymentLabLiveStepStatus.ACTIVE
    )

    failure_status = PaymentLabLiveStepStatus.PENDING
    if payment_attempt is not None:
        failure_status = PaymentLabLiveStepStatus.COMPLETED
    elif provider_failed or run_expired:
        failure_status = PaymentLabLiveStepStatus.FAILED
    elif run.status == PaymentLabRunStatus.CHECKOUT_READY.value:
        failure_status = PaymentLabLiveStepStatus.ACTIVE

    case_status = PaymentLabLiveStepStatus.PENDING
    if recovery_case is not None:
        case_status = PaymentLabLiveStepStatus.COMPLETED
    elif payment_attempt is not None:
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

    provider_status = PaymentLabLiveStepStatus.PENDING
    if latest_action is not None:
        if latest_action.status == "succeeded":
            provider_status = PaymentLabLiveStepStatus.COMPLETED
        elif latest_action.status == "failed":
            provider_status = PaymentLabLiveStepStatus.FAILED
        elif latest_action.policy_outcome in {"block", "escalate", "stop"}:
            provider_status = PaymentLabLiveStepStatus.COMPLETED
        else:
            provider_status = PaymentLabLiveStepStatus.ACTIVE

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
            label="Verified failure",
            status=failure_status,
            occurred_at=(
                payment_attempt.state_event_created_at if payment_attempt is not None else None
            ),
            detail=(
                "Signed provider evidence linked"
                if payment_attempt is not None
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
            key="provider_action",
            label=(
                "Safe disposition"
                if latest_action is not None
                and latest_action.policy_outcome in {"block", "escalate", "stop"}
                else "Provider action"
            ),
            status=provider_status,
            occurred_at=(
                latest_action.completed_at or latest_action.started_at or latest_action.created_at
                if latest_action is not None
                else None
            ),
            detail=(
                "Razorpay payment link created"
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

        outcome_result = await session.execute(
            select(RecoveryOutcome).where(
                RecoveryOutcome.recovery_case_id == recovery_case.id,
            ),
        )
        outcome = outcome_result.scalar_one_or_none()

    terminal = _derive_terminal(run, recovery_case, outcome)
    return PaymentLabLiveRun(
        payment_lab_run_id=run.id,
        client_request_id=run.client_request_id,
        mode=run.mode,
        provenance=run.provenance,
        persisted_status=run.status,
        current_stage=_derive_stage(
            run,
            payment_attempt=payment_attempt,
            recovery_case=recovery_case,
            agent_run=agent_run,
            actions=actions,
            outcome=outcome,
        ),
        terminal=terminal,
        poll_after_milliseconds=None if terminal else 500,
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
            payment_attempt=payment_attempt,
            recovery_case=recovery_case,
            agent_run=agent_run,
            actions=actions,
            outcome=outcome,
        ),
        payment=_build_payment_evidence(payment_attempt),
        agent=_build_agent_evidence(recovery_case, agent_run),
        actions=_build_action_evidence(actions),
        outcome=_build_outcome_evidence(outcome),
    )
