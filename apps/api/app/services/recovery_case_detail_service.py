from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt, PaymentStateTransition
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryAgentRun,
    RecoveryApproval,
    RecoveryCase,
)
from app.db.models.recovery_outcome import RecoveryOutcome
from app.services.recovery_ai_trace import RecoveryAiTrace, build_recovery_ai_trace
from app.services.recovery_audit import (
    RecoveryAuditChainEntry,
    RecoveryAuditVerification,
)
from app.services.recovery_audit_store import (
    load_recovery_audit_chain,
    verify_persisted_recovery_audit_chain,
)

MAX_AGENT_RUN_SUMMARIES: Final = 10
MAX_ACTION_SUMMARIES: Final = 50
MAX_PAYMENT_TRANSITIONS: Final = 50
MAX_AUDIT_EVENTS: Final = 100


class RecoveryCaseDetailNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryCaseSnapshot:
    recovery_case_id: UUID
    status: str
    amount_minor: int
    currency: str
    payment_method: str | None
    source_incident_id: UUID | None
    recovery_attempt_count: int
    active_payment_link_id: str | None
    next_action_at: datetime | None
    late_authorization_detected_at: datetime | None
    opened_at: datetime
    recovered_at: datetime | None
    closed_at: datetime | None
    close_reason: str | None


@dataclass(frozen=True, slots=True)
class PaymentLifecycleSnapshot:
    payment_attempt_id: UUID
    current_state: str
    state_version: int
    amount_minor: int
    currency: str
    payment_method: str | None
    error_code: str | None
    error_source: str | None
    error_step: str | None
    error_reason: str | None
    recovery_eligible: bool
    recovery_stopped_at: datetime | None
    recovery_stop_reason: str | None
    late_authorization_detected_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecoveryAgentRunSummary:
    agent_run_id: UUID
    run_number: int
    status: str
    planner_provider: str
    model_name: str | None
    prompt_version: str
    reasoning_summary: str | None
    proposed_action_count: int
    failure_code: str | None
    started_at: datetime
    completed_at: datetime | None
    ai_trace: RecoveryAiTrace


@dataclass(frozen=True, slots=True)
class RecoveryActionSummary:
    recovery_action_id: UUID
    agent_run_id: UUID
    sequence_number: int
    action_type: str
    status: str
    proposal_reason: str
    amount_minor: int | None
    currency: str | None
    channel: str | None
    target_payment_method: str | None
    execute_after: datetime | None
    policy_outcome: str
    policy_guardrails: tuple[str, ...]
    policy_explanation: str
    policy_version: str
    policy_evaluated_at: datetime
    execution_attempt_count: int
    provider_action_id: str | None
    provider_action_status: str | None
    provider_action_url: str | None
    provider_action_expires_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecoveryApprovalSummary:
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
class RecoveryOutcomeSummary:
    recovery_outcome_id: UUID
    status: str
    attribution: str
    recovery_action_id: UUID | None
    payment_link_id: str | None
    gross_recovered_minor: int
    reversed_minor: int
    duplicate_collection_prevented_minor: int
    evidence_event_count: int
    occurred_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentTransitionSummary:
    event_type: str
    previous_state: str
    incoming_state: str
    resulting_state: str
    resulting_version: int
    outcome: str
    reason: str
    late_authorization: bool
    stop_recovery: bool
    event_created_at: datetime
    processed_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryAuditEventSummary:
    sequence_number: int
    event_type: str
    actor_type: str
    recovery_action_id: UUID | None
    previous_event_hash: str | None
    event_hash: str
    hash_algorithm: str
    occurred_at: datetime
    provider_status: str | None = None
    outcome_status: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryAuditChainSummary:
    valid: bool
    reason: str
    checked_event_count: int
    broken_sequence_number: int | None
    total_event_count: int
    timeline_truncated: bool
    events: tuple[RecoveryAuditEventSummary, ...]


@dataclass(frozen=True, slots=True)
class RecoveryCaseDetail:
    recovery_case: RecoveryCaseSnapshot
    payment_lifecycle: PaymentLifecycleSnapshot
    agent_runs: tuple[RecoveryAgentRunSummary, ...]
    actions: tuple[RecoveryActionSummary, ...]
    outcome: RecoveryOutcomeSummary | None
    payment_transitions: tuple[PaymentTransitionSummary, ...]
    audit_chain: RecoveryAuditChainSummary
    approvals: tuple[RecoveryApprovalSummary, ...] = ()


def build_recovery_case_snapshot(case: RecoveryCase) -> RecoveryCaseSnapshot:
    return RecoveryCaseSnapshot(
        recovery_case_id=case.id,
        status=case.status,
        amount_minor=case.amount_minor,
        currency=case.currency,
        payment_method=case.payment_method,
        source_incident_id=case.source_incident_id,
        recovery_attempt_count=case.recovery_attempt_count,
        active_payment_link_id=case.active_payment_link_id,
        next_action_at=case.next_action_at,
        late_authorization_detected_at=case.late_authorization_detected_at,
        opened_at=case.opened_at,
        recovered_at=case.recovered_at,
        closed_at=case.closed_at,
        close_reason=case.close_reason,
    )


def build_payment_lifecycle_snapshot(
    payment_attempt: PaymentAttempt,
) -> PaymentLifecycleSnapshot:
    return PaymentLifecycleSnapshot(
        payment_attempt_id=payment_attempt.id,
        current_state=payment_attempt.current_state,
        state_version=payment_attempt.state_version,
        amount_minor=payment_attempt.amount_minor,
        currency=payment_attempt.currency,
        payment_method=payment_attempt.method,
        error_code=payment_attempt.error_code,
        error_source=payment_attempt.error_source,
        error_step=payment_attempt.error_step,
        error_reason=payment_attempt.error_reason,
        recovery_eligible=payment_attempt.recovery_eligible,
        recovery_stopped_at=payment_attempt.recovery_stopped_at,
        recovery_stop_reason=payment_attempt.recovery_stop_reason,
        late_authorization_detected_at=payment_attempt.late_authorization_detected_at,
    )


def build_agent_run_summary(agent_run: RecoveryAgentRun) -> RecoveryAgentRunSummary:
    return RecoveryAgentRunSummary(
        agent_run_id=agent_run.id,
        run_number=agent_run.run_number,
        status=agent_run.status,
        planner_provider=agent_run.planner_provider,
        model_name=agent_run.model_name,
        prompt_version=agent_run.prompt_version,
        reasoning_summary=agent_run.reasoning_summary,
        proposed_action_count=agent_run.proposed_action_count,
        failure_code=agent_run.failure_code,
        started_at=agent_run.started_at,
        completed_at=agent_run.completed_at,
        ai_trace=build_recovery_ai_trace(agent_run.evidence),
    )


def build_action_summary(action: RecoveryAction) -> RecoveryActionSummary:
    return RecoveryActionSummary(
        recovery_action_id=action.id,
        agent_run_id=action.agent_run_id,
        sequence_number=action.sequence_number,
        action_type=action.action_type,
        status=action.status,
        proposal_reason=action.proposal_reason,
        amount_minor=action.amount_minor,
        currency=action.currency,
        channel=action.channel,
        target_payment_method=action.target_payment_method,
        execute_after=action.execute_after,
        policy_outcome=action.policy_outcome,
        policy_guardrails=tuple(action.policy_guardrails),
        policy_explanation=action.policy_explanation,
        policy_version=action.policy_version,
        policy_evaluated_at=action.policy_evaluated_at,
        execution_attempt_count=action.execution_attempt_count,
        provider_action_id=action.provider_action_id,
        provider_action_status=action.provider_action_status,
        provider_action_url=action.provider_action_url,
        provider_action_expires_at=action.provider_action_expires_at,
        started_at=action.started_at,
        completed_at=action.completed_at,
    )


def build_approval_summary(approval: RecoveryApproval) -> RecoveryApprovalSummary:
    return RecoveryApprovalSummary(
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


def build_outcome_summary(outcome: RecoveryOutcome) -> RecoveryOutcomeSummary:
    return RecoveryOutcomeSummary(
        recovery_outcome_id=outcome.id,
        status=outcome.status,
        attribution=outcome.attribution,
        recovery_action_id=outcome.recovery_action_id,
        payment_link_id=outcome.payment_link_id,
        gross_recovered_minor=outcome.gross_recovered_minor,
        reversed_minor=outcome.reversed_minor,
        duplicate_collection_prevented_minor=(outcome.duplicate_collection_prevented_minor),
        evidence_event_count=len(outcome.evidence_event_ids),
        occurred_at=outcome.occurred_at,
        updated_at=outcome.updated_at,
    )


def build_payment_transition_summary(
    transition: PaymentStateTransition,
) -> PaymentTransitionSummary:
    return PaymentTransitionSummary(
        event_type=transition.event_type,
        previous_state=transition.previous_state,
        incoming_state=transition.incoming_state,
        resulting_state=transition.resulting_state,
        resulting_version=transition.resulting_version,
        outcome=transition.outcome,
        reason=transition.reason,
        late_authorization=transition.late_authorization,
        stop_recovery=transition.stop_recovery,
        event_created_at=transition.event_created_at,
        processed_at=transition.processed_at,
    )


def build_audit_chain_summary(
    *,
    entries: tuple[RecoveryAuditChainEntry, ...],
    verification: RecoveryAuditVerification,
) -> RecoveryAuditChainSummary:
    timeline_entries = entries[:MAX_AUDIT_EVENTS]

    return RecoveryAuditChainSummary(
        valid=verification.valid,
        reason=verification.reason.value,
        checked_event_count=verification.checked_event_count,
        broken_sequence_number=verification.broken_sequence_number,
        total_event_count=len(entries),
        timeline_truncated=len(entries) > MAX_AUDIT_EVENTS,
        events=tuple(
            RecoveryAuditEventSummary(
                sequence_number=entry.sequence_number,
                event_type=entry.event_type,
                actor_type=entry.actor_type,
                recovery_action_id=entry.recovery_action_id,
                previous_event_hash=entry.previous_event_hash,
                event_hash=entry.event_hash,
                hash_algorithm=entry.hash_algorithm,
                occurred_at=entry.occurred_at,
                provider_status=(
                    entry.event_data.get("provider_status")
                    if isinstance(entry.event_data.get("provider_status"), str)
                    else None
                ),
                outcome_status=(
                    entry.event_data.get("outcome_status")
                    if isinstance(entry.event_data.get("outcome_status"), str)
                    else None
                ),
            )
            for entry in timeline_entries
        ),
    )


async def load_recovery_case_detail(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
) -> RecoveryCaseDetail:
    case_result = await session.execute(
        select(RecoveryCase, PaymentAttempt, RecoveryOutcome)
        .join(
            PaymentAttempt,
            PaymentAttempt.id == RecoveryCase.payment_attempt_id,
        )
        .outerjoin(
            RecoveryOutcome,
            RecoveryOutcome.recovery_case_id == RecoveryCase.id,
        )
        .where(RecoveryCase.id == recovery_case_id),
    )
    row = case_result.one_or_none()

    if row is None:
        raise RecoveryCaseDetailNotFoundError(
            f"Recovery case {recovery_case_id} does not exist",
        )

    recovery_case, payment_attempt, outcome = row

    agent_runs_result = await session.execute(
        select(RecoveryAgentRun)
        .where(RecoveryAgentRun.recovery_case_id == recovery_case_id)
        .order_by(RecoveryAgentRun.run_number.desc())
        .limit(MAX_AGENT_RUN_SUMMARIES),
    )
    actions_result = await session.execute(
        select(RecoveryAction)
        .where(RecoveryAction.recovery_case_id == recovery_case_id)
        .order_by(RecoveryAction.sequence_number)
        .limit(MAX_ACTION_SUMMARIES),
    )
    approvals_result = await session.execute(
        select(RecoveryApproval)
        .where(RecoveryApproval.recovery_case_id == recovery_case_id)
        .order_by(RecoveryApproval.requested_at, RecoveryApproval.id),
    )
    transitions_result = await session.execute(
        select(PaymentStateTransition)
        .where(PaymentStateTransition.payment_attempt_id == payment_attempt.id)
        .order_by(
            PaymentStateTransition.event_created_at,
            PaymentStateTransition.id,
        )
        .limit(MAX_PAYMENT_TRANSITIONS),
    )

    audit_entries = await load_recovery_audit_chain(
        session,
        recovery_case_id=recovery_case_id,
    )
    audit_verification = await verify_persisted_recovery_audit_chain(
        session,
        recovery_case_id=recovery_case_id,
    )

    return RecoveryCaseDetail(
        recovery_case=build_recovery_case_snapshot(recovery_case),
        payment_lifecycle=build_payment_lifecycle_snapshot(payment_attempt),
        agent_runs=tuple(
            build_agent_run_summary(agent_run) for agent_run in agent_runs_result.scalars().all()
        ),
        actions=tuple(build_action_summary(action) for action in actions_result.scalars().all()),
        approvals=tuple(
            build_approval_summary(approval) for approval in approvals_result.scalars().all()
        ),
        outcome=build_outcome_summary(outcome) if outcome is not None else None,
        payment_transitions=tuple(
            build_payment_transition_summary(transition)
            for transition in transitions_result.scalars().all()
        ),
        audit_chain=build_audit_chain_summary(
            entries=audit_entries,
            verification=audit_verification,
        ),
    )
