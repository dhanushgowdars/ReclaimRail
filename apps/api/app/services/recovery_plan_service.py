import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAgentRun,
    RecoveryAgentRunStatus,
    RecoveryApproval,
    RecoveryAuditActor,
    RecoveryAuditEvent,
    RecoveryCase,
    RecoveryPlannerProvider,
)
from app.domain.incidents import IncidentSeverity
from app.domain.payments import PaymentState
from app.domain.recovery import (
    PaymentFailureEvidence,
    RecoveryActionProposal,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlan,
    RecoveryPlanDecision,
    RecoveryPlanningContext,
    RecoveryPolicyDecision,
    RecoveryPolicyOutcome,
    build_deterministic_recovery_plan,
    evaluate_recovery_proposal,
)
from app.integrations.gemini import (
    BoundedRecoveryPlannerResult,
    GeminiPlannerFallbackReason,
    RecoveryPlannerSource,
    build_recovery_evidence_tools,
)
from app.services.recovery_approval_service import (
    DEFAULT_APPROVAL_THRESHOLD_MINOR,
    DEFAULT_APPROVAL_WINDOW,
    build_recovery_approval_requirement,
    create_recovery_approval_request,
)
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)
from app.services.recovery_incident_context import (
    ActiveRecoveryIncidentContext,
    load_active_recovery_incident_context,
)

PLANNABLE_CASE_STATUSES = frozenset(
    {
        RecoveryCaseStatus.OPEN,
        RecoveryCaseStatus.WAITING,
    },
)


class RecoveryPlanningCaseNotFoundError(LookupError):
    pass


class RecoveryPlanningPaymentNotFoundError(LookupError):
    pass


class RecoveryCaseNotPlannableError(ValueError):
    pass


class RecoveryPlannerResultMismatchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedRecoveryPlan:
    plan: RecoveryPlan
    agent_run: RecoveryAgentRun
    actions: tuple[RecoveryAction, ...]
    approvals: tuple[RecoveryApproval, ...]
    audit_event: RecoveryAuditEvent


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Recovery planning time must be timezone-aware")


def _serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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


def _build_planning_context(
    recovery_case: RecoveryCase,
    payment_attempt: PaymentAttempt,
    *,
    incident_severity: IncidentSeverity | None,
    available_channels: Sequence[RecoveryChannel],
    alternate_payment_methods: Sequence[str],
    planned_at: datetime,
) -> RecoveryPlanningContext:
    failure_timestamp = payment_attempt.state_event_created_at

    return RecoveryPlanningContext(
        case=_build_case_snapshot(
            recovery_case,
            payment_attempt,
            incident_severity=incident_severity,
        ),
        failure=PaymentFailureEvidence(
            error_code=payment_attempt.error_code,
            error_source=payment_attempt.error_source,
            error_step=payment_attempt.error_step,
            error_reason=payment_attempt.error_reason,
            failure_count=1,
            first_failed_at=failure_timestamp,
            last_failed_at=failure_timestamp,
        ),
        available_channels=tuple(available_channels),
        alternate_payment_methods=tuple(alternate_payment_methods),
        planned_at=planned_at,
    )


def _input_snapshot(context: RecoveryPlanningContext) -> dict[str, object]:
    case = context.case

    return {
        "case_id": str(case.case_id),
        "payment_attempt_id": str(case.payment_attempt_id),
        "provider_payment_id": case.provider_payment_id,
        "payment_state": case.payment_state.value,
        "amount_minor": case.amount_minor,
        "currency": case.currency,
        "payment_method": case.payment_method,
        "case_status": case.status.value,
        "recovery_attempt_count": case.recovery_attempt_count,
        "customer_contact_allowed": case.customer_contact_allowed,
        "last_customer_contact_at": _serialize_timestamp(
            case.last_customer_contact_at,
        ),
        "active_payment_link_id": case.active_payment_link_id,
        "active_incident_severity": (
            case.active_incident_severity.value
            if case.active_incident_severity is not None
            else None
        ),
        "late_authorization_detected_at": _serialize_timestamp(
            case.late_authorization_detected_at,
        ),
    }


def _planning_evidence(
    context: RecoveryPlanningContext,
    plan: RecoveryPlan,
    planner_result: BoundedRecoveryPlannerResult,
) -> dict[str, object]:
    failure = context.failure

    return {
        "evidence_codes": list(plan.evidence_codes),
        "failure": {
            "error_code": failure.error_code,
            "error_source": failure.error_source,
            "error_step": failure.error_step,
            "error_reason": failure.error_reason,
            "failure_count": failure.failure_count,
            "first_failed_at": failure.first_failed_at.isoformat(),
            "last_failed_at": failure.last_failed_at.isoformat(),
        },
        "available_channels": [channel.value for channel in context.available_channels],
        "alternate_payment_methods": list(
            context.alternate_payment_methods,
        ),
        "planner": {
            "source": planner_result.source.value,
            "model_name": planner_result.model_name,
            "fallback_used": planner_result.fallback_used,
            "fallback_reason": (
                planner_result.fallback_reason.value
                if planner_result.fallback_reason is not None
                else None
            ),
            "input_token_count": planner_result.input_token_count,
            "output_token_count": planner_result.output_token_count,
        },
        "bounded_ai_analysis": (
            {
                "root_cause_category": planner_result.analysis.root_cause_category,
                "recoverability_assessment": planner_result.analysis.recoverability_assessment,
                "confidence": planner_result.analysis.confidence,
                "allowed_action_recommendation": (
                    planner_result.analysis.allowed_action_recommendation
                ),
                "evidence_references": list(planner_result.analysis.evidence_references),
                "operator_explanation": planner_result.analysis.operator_explanation,
            }
            if planner_result.analysis is not None
            else None
        ),
        "bounded_ai_evidence_tools": build_recovery_evidence_tools(context),
    }


def _action_status(
    proposal: RecoveryActionProposal,
    decision: RecoveryPolicyDecision,
    *,
    planned_at: datetime,
) -> RecoveryActionStatus:
    if decision.outcome is RecoveryPolicyOutcome.BLOCK:
        return RecoveryActionStatus.BLOCKED

    if decision.outcome is RecoveryPolicyOutcome.ESCALATE:
        return RecoveryActionStatus.ESCALATED

    if decision.outcome is RecoveryPolicyOutcome.STOP:
        return RecoveryActionStatus.STOPPED

    if proposal.execute_after is not None and proposal.execute_after > planned_at:
        return RecoveryActionStatus.SCHEDULED

    return RecoveryActionStatus.ALLOWED


def _action_idempotency_key(
    *,
    recovery_case_id: UUID,
    run_number: int,
    sequence_number: int,
    proposal: RecoveryActionProposal,
) -> str:
    material = f"{recovery_case_id}:{run_number}:{sequence_number}:{proposal.action_type.value}"

    return hashlib.sha256(
        material.encode("utf-8"),
    ).hexdigest()


def _apply_case_projection(
    recovery_case: RecoveryCase,
    *,
    plan: RecoveryPlan,
    actions: Sequence[RecoveryAction],
    planned_at: datetime,
) -> None:
    if any(action.status == RecoveryActionStatus.STOPPED.value for action in actions):
        recovery_case.status = RecoveryCaseStatus.CANCELLED.value
        recovery_case.next_action_at = None
        recovery_case.closed_at = planned_at
        recovery_case.close_reason = "bounded_plan_stop"

    elif any(action.status == RecoveryActionStatus.ESCALATED.value for action in actions):
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None

    elif any(action.status == RecoveryActionStatus.APPROVAL_REQUIRED.value for action in actions):
        recovery_case.status = RecoveryCaseStatus.AWAITING_APPROVAL.value
        recovery_case.next_action_at = None

    elif plan.decision is RecoveryPlanDecision.WAIT:
        recovery_case.status = RecoveryCaseStatus.WAITING.value
        recovery_case.next_action_at = min(
            action.execute_after for action in actions if action.execute_after is not None
        )

    elif any(action.status == RecoveryActionStatus.ALLOWED.value for action in actions):
        recovery_case.status = RecoveryCaseStatus.READY.value
        recovery_case.next_action_at = planned_at

    else:
        recovery_case.status = RecoveryCaseStatus.WAITING.value
        recovery_case.next_action_at = None

    recovery_case.version += 1


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


async def load_recovery_planning_context(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
    available_channels: Sequence[RecoveryChannel],
    alternate_payment_methods: Sequence[str],
    planned_at: datetime,
) -> RecoveryPlanningContext:
    """Load a read-only planning snapshot without holding row locks."""

    _require_timezone_aware(planned_at)

    case_result = await session.execute(
        select(RecoveryCase).where(
            RecoveryCase.id == recovery_case_id,
        ),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryPlanningCaseNotFoundError(
            f"Recovery case {recovery_case_id} does not exist",
        )

    case_status = RecoveryCaseStatus(
        recovery_case.status,
    )

    if case_status not in PLANNABLE_CASE_STATUSES:
        raise RecoveryCaseNotPlannableError(
            f"Recovery case {recovery_case_id} cannot be planned from {case_status.value}",
        )

    payment_result = await session.execute(
        select(PaymentAttempt).where(
            PaymentAttempt.id == recovery_case.payment_attempt_id,
        ),
    )
    payment_attempt = payment_result.scalar_one_or_none()

    if payment_attempt is None:
        raise RecoveryPlanningPaymentNotFoundError(
            f"Payment attempt {recovery_case.payment_attempt_id} does not exist",
        )

    incident_context = await _load_active_incident_context(
        session,
        recovery_case=recovery_case,
    )

    return _build_planning_context(
        recovery_case,
        payment_attempt,
        incident_severity=(incident_context.severity if incident_context is not None else None),
        available_channels=available_channels,
        alternate_payment_methods=alternate_payment_methods,
        planned_at=planned_at,
    )


def _deterministic_planner_result(
    context: RecoveryPlanningContext,
) -> BoundedRecoveryPlannerResult:
    return BoundedRecoveryPlannerResult(
        plan=build_deterministic_recovery_plan(
            context,
        ),
        source=RecoveryPlannerSource.DETERMINISTIC,
        model_name=None,
        fallback_used=True,
        fallback_reason=(GeminiPlannerFallbackReason.NOT_CONFIGURED),
    )


async def plan_and_persist_recovery_case(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
    available_channels: Sequence[RecoveryChannel],
    alternate_payment_methods: Sequence[str],
    planned_at: datetime,
    planner_result: BoundedRecoveryPlannerResult | None = None,
    agent_started_at: datetime | None = None,
    agent_completed_at: datetime | None = None,
    approval_threshold_minor: int = DEFAULT_APPROVAL_THRESHOLD_MINOR,
    approval_window: timedelta = DEFAULT_APPROVAL_WINDOW,
) -> PersistedRecoveryPlan:
    _require_timezone_aware(planned_at)
    if agent_started_at is not None:
        _require_timezone_aware(agent_started_at)
    if agent_completed_at is not None:
        _require_timezone_aware(agent_completed_at)
    if (
        agent_started_at is not None
        and agent_completed_at is not None
        and agent_completed_at < agent_started_at
    ):
        raise ValueError("Recovery agent completion cannot precede its start")
    if approval_threshold_minor < 1:
        raise ValueError("Approval threshold must be positive")
    if approval_window <= timedelta(0):
        raise ValueError("Approval window must be positive")

    case_result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryPlanningCaseNotFoundError(
            f"Recovery case {recovery_case_id} does not exist",
        )

    case_status = RecoveryCaseStatus(
        recovery_case.status,
    )

    if case_status not in PLANNABLE_CASE_STATUSES:
        raise RecoveryCaseNotPlannableError(
            f"Recovery case {recovery_case_id} cannot be planned from {case_status.value}",
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
        raise RecoveryPlanningPaymentNotFoundError(
            f"Payment attempt {recovery_case.payment_attempt_id} does not exist",
        )

    incident_context = await _load_active_incident_context(
        session,
        recovery_case=recovery_case,
    )

    context = _build_planning_context(
        recovery_case,
        payment_attempt,
        incident_severity=(incident_context.severity if incident_context is not None else None),
        available_channels=available_channels,
        alternate_payment_methods=alternate_payment_methods,
        planned_at=planned_at,
    )

    if planner_result is None:
        planner_result = _deterministic_planner_result(
            context,
        )

    plan = planner_result.plan

    if plan.generated_at != planned_at:
        raise RecoveryPlannerResultMismatchError(
            "Planner result timestamp does not match the persistence attempt",
        )

    run_number_result = await session.execute(
        select(
            func.coalesce(
                func.max(
                    RecoveryAgentRun.run_number,
                ),
                0,
            ),
        ).where(
            RecoveryAgentRun.recovery_case_id == recovery_case_id,
        ),
    )
    run_number = (
        int(
            run_number_result.scalar_one(),
        )
        + 1
    )

    agent_run = RecoveryAgentRun(
        id=uuid4(),
        recovery_case_id=recovery_case_id,
        run_number=run_number,
        status=RecoveryAgentRunStatus.SUCCEEDED.value,
        planner_provider=RecoveryPlannerProvider(
            planner_result.source.value,
        ).value,
        model_name=planner_result.model_name,
        prompt_version=plan.planner_version,
        input_snapshot={
            **_input_snapshot(context),
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
        evidence=_planning_evidence(
            context,
            plan,
            planner_result,
        ),
        reasoning_summary=plan.reasoning_summary,
        proposed_action_count=len(
            plan.proposals,
        ),
        input_token_count=(planner_result.input_token_count),
        output_token_count=(planner_result.output_token_count),
        # Direct deterministic callers may not have an externally measured
        # execution window yet. Preserve their existing planned timestamp while
        # normal agent execution supplies actual provider-call bounds.
        started_at=agent_started_at or planned_at,
        completed_at=agent_completed_at or planned_at,
    )

    session.add(
        agent_run,
    )
    await session.flush()

    actions: list[RecoveryAction] = []
    for sequence_number, proposal in enumerate(
        plan.proposals,
        start=1,
    ):
        policy_decision = evaluate_recovery_proposal(
            context.case,
            proposal,
            evaluated_at=planned_at,
        )

        status = _action_status(
            proposal,
            policy_decision,
            planned_at=planned_at,
        )

        action = RecoveryAction(
            id=uuid4(),
            recovery_case_id=recovery_case_id,
            agent_run_id=agent_run.id,
            sequence_number=sequence_number,
            idempotency_key=_action_idempotency_key(
                recovery_case_id=recovery_case_id,
                run_number=run_number,
                sequence_number=sequence_number,
                proposal=proposal,
            ),
            action_type=proposal.action_type.value,
            status=status.value,
            proposal_reason=proposal.reason,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            channel=(proposal.channel.value if proposal.channel is not None else None),
            target_payment_method=(proposal.target_payment_method),
            execute_after=proposal.execute_after,
            policy_outcome=(policy_decision.outcome.value),
            policy_guardrails=[guardrail.value for guardrail in policy_decision.guardrails],
            policy_explanation=(policy_decision.explanation),
            policy_version="deterministic-v1",
            policy_evaluated_at=(policy_decision.evaluated_at),
            execution_attempt_count=0,
        )

        session.add(
            action,
        )
        actions.append(
            action,
        )

    await session.flush()

    approval_requirements = {
        action.id: requirement
        for action in actions
        if (
            requirement := build_recovery_approval_requirement(
                action,
                threshold_minor=approval_threshold_minor,
                recovery_attempt_count=recovery_case.recovery_attempt_count,
                active_incident_severity=(
                    incident_context.severity if incident_context is not None else None
                ),
                ai_confidence=(
                    planner_result.analysis.confidence
                    if planner_result.analysis is not None
                    else None
                ),
            )
        )
        is not None
    }
    approval_actions = tuple(action for action in actions if action.id in approval_requirements)
    for action in approval_actions:
        action.status = RecoveryActionStatus.APPROVAL_REQUIRED.value

    _apply_case_projection(
        recovery_case,
        plan=plan,
        actions=actions,
        planned_at=planned_at,
    )

    audit_event = await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case_id,
        request=RecoveryAuditAppendRequest(
            event_type="agent.plan.persisted",
            actor_type=RecoveryAuditActor.AGENT,
            agent_run_id=agent_run.id,
            event_data={
                "run_number": run_number,
                "planner_provider": (agent_run.planner_provider),
                "model_name": agent_run.model_name,
                "planner_version": (plan.planner_version),
                "fallback_used": (planner_result.fallback_used),
                "fallback_reason": (
                    planner_result.fallback_reason.value
                    if planner_result.fallback_reason is not None
                    else None
                ),
                "input_token_count": (planner_result.input_token_count),
                "output_token_count": (planner_result.output_token_count),
                "plan_decision": plan.decision,
                "reasoning_summary": (plan.reasoning_summary),
                "bounded_ai_analysis": (
                    {
                        "root_cause_category": planner_result.analysis.root_cause_category,
                        "confidence": planner_result.analysis.confidence,
                        "evidence_references": list(planner_result.analysis.evidence_references),
                    }
                    if planner_result.analysis is not None
                    else None
                ),
                "actions": [
                    {
                        "action_id": action.id,
                        "sequence_number": action.sequence_number,
                        "action_type": action.action_type,
                        "status": action.status,
                        "policy_outcome": action.policy_outcome,
                        "policy_guardrails": action.policy_guardrails,
                    }
                    for action in actions
                ],
            },
            occurred_at=planned_at,
        ),
    )

    approvals: list[RecoveryApproval] = []
    for action in approval_actions:
        approvals.append(
            await create_recovery_approval_request(
                session,
                recovery_case=recovery_case,
                action=action,
                requirement=approval_requirements[action.id],
                requested_at=planned_at,
                approval_window=approval_window,
            ),
        )

    return PersistedRecoveryPlan(
        plan=plan,
        agent_run=agent_run,
        actions=tuple(
            actions,
        ),
        approvals=tuple(approvals),
        audit_event=audit_event,
    )
