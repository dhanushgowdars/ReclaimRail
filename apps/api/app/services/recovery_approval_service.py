from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryApproval,
    RecoveryApprovalStatus,
    RecoveryAuditActor,
    RecoveryCase,
)
from app.domain.recovery import RecoveryCaseStatus
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)

DEFAULT_APPROVAL_THRESHOLD_MINOR = 1_000_000
DEFAULT_APPROVAL_WINDOW = timedelta(minutes=15)
APPROVAL_REQUEST_REASON = "amount_requires_operator_approval"


class RecoveryApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RecoveryApprovalDecisionDisposition(StrEnum):
    DECIDED = "decided"
    ALREADY_DECIDED = "already_decided"
    EXPIRED = "expired"


class RecoveryApprovalNotFoundError(LookupError):
    pass


class RecoveryApprovalConflictError(RuntimeError):
    pass


class RecoveryApprovalStateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryApprovalDecisionResult:
    approval: RecoveryApproval
    disposition: RecoveryApprovalDecisionDisposition


def _require_timezone_aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _normalize_required_text(
    value: str,
    *,
    field_name: str,
    maximum_length: int,
) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if len(normalized) > maximum_length:
        raise ValueError(f"{field_name} cannot exceed {maximum_length} characters")
    return normalized


def action_requires_human_approval(
    action: RecoveryAction,
    *,
    threshold_minor: int,
) -> bool:
    if threshold_minor < 1:
        raise ValueError("Approval threshold must be positive")
    return (
        action.status
        in {
            RecoveryActionStatus.ALLOWED.value,
            RecoveryActionStatus.APPROVAL_REQUIRED.value,
        }
        and action.action_type == "create_payment_link"
        and action.amount_minor is not None
        and action.amount_minor >= threshold_minor
    )


async def create_recovery_approval_request(
    session: AsyncSession,
    *,
    recovery_case: RecoveryCase,
    action: RecoveryAction,
    threshold_minor: int,
    requested_at: datetime,
    approval_window: timedelta,
) -> RecoveryApproval:
    _require_timezone_aware(requested_at, field_name="Approval request time")
    if threshold_minor < 1:
        raise ValueError("Approval threshold must be positive")
    if approval_window <= timedelta(0):
        raise ValueError("Approval window must be positive")
    if not action_requires_human_approval(action, threshold_minor=threshold_minor):
        raise RecoveryApprovalStateError(
            f"Recovery action {action.id} does not require approval",
        )
    if action.amount_minor is None or action.currency is None:
        raise RecoveryApprovalStateError(
            f"Recovery action {action.id} has no monetary approval input",
        )

    approval = RecoveryApproval(
        id=uuid4(),
        recovery_case_id=recovery_case.id,
        recovery_action_id=action.id,
        status=RecoveryApprovalStatus.PENDING.value,
        request_reason=APPROVAL_REQUEST_REASON,
        amount_minor=action.amount_minor,
        currency=action.currency,
        threshold_minor=threshold_minor,
        requested_at=requested_at,
        expires_at=requested_at + approval_window,
        version=0,
    )
    action.status = RecoveryActionStatus.APPROVAL_REQUIRED.value
    session.add(approval)
    await session.flush()

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="approval.requested",
            actor_type=RecoveryAuditActor.POLICY,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "approval_id": str(approval.id),
                "request_reason": approval.request_reason,
                "amount_minor": approval.amount_minor,
                "currency": approval.currency,
                "threshold_minor": approval.threshold_minor,
                "expires_at": approval.expires_at.isoformat(),
            },
            occurred_at=requested_at,
        ),
    )
    return approval


async def _load_approval_graph_for_update(
    session: AsyncSession,
    *,
    approval_id: UUID,
) -> tuple[RecoveryApproval, RecoveryAction, RecoveryCase]:
    approval_result = await session.execute(
        select(RecoveryApproval).where(RecoveryApproval.id == approval_id).with_for_update(),
    )
    approval = approval_result.scalar_one_or_none()
    if approval is None:
        raise RecoveryApprovalNotFoundError(
            f"Recovery approval {approval_id} does not exist",
        )

    action_result = await session.execute(
        select(RecoveryAction)
        .where(RecoveryAction.id == approval.recovery_action_id)
        .with_for_update(),
    )
    action = action_result.scalar_one_or_none()
    case_result = await session.execute(
        select(RecoveryCase).where(RecoveryCase.id == approval.recovery_case_id).with_for_update(),
    )
    recovery_case = case_result.scalar_one_or_none()
    if action is None or recovery_case is None:
        raise RecoveryApprovalStateError(
            f"Recovery approval {approval_id} has incomplete execution state",
        )
    return approval, action, recovery_case


async def _expire_approval(
    session: AsyncSession,
    *,
    approval: RecoveryApproval,
    action: RecoveryAction,
    recovery_case: RecoveryCase,
    expired_at: datetime,
) -> None:
    approval.status = RecoveryApprovalStatus.EXPIRED.value
    approval.decided_at = expired_at
    approval.decided_by = None
    approval.decision_reason = "Approval window expired before an operator decision"
    approval.version += 1
    action.status = RecoveryActionStatus.CANCELLED.value
    action.completed_at = expired_at
    if recovery_case.status == RecoveryCaseStatus.AWAITING_APPROVAL.value:
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None
        recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="approval.expired",
            actor_type=RecoveryAuditActor.SYSTEM,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "approval_id": str(approval.id),
                "approval_version": approval.version,
                "expires_at": approval.expires_at.isoformat(),
            },
            occurred_at=expired_at,
        ),
    )


async def decide_recovery_approval(
    session: AsyncSession,
    *,
    approval_id: UUID,
    decision: RecoveryApprovalDecision,
    reviewer_id: str,
    reason: str,
    expected_version: int,
    decided_at: datetime,
) -> RecoveryApprovalDecisionResult:
    _require_timezone_aware(decided_at, field_name="Approval decision time")
    if expected_version < 0:
        raise ValueError("Expected approval version cannot be negative")
    normalized_reviewer = _normalize_required_text(
        reviewer_id,
        field_name="Reviewer ID",
        maximum_length=128,
    )
    normalized_reason = _normalize_required_text(
        reason,
        field_name="Decision reason",
        maximum_length=1000,
    )
    approval, action, recovery_case = await _load_approval_graph_for_update(
        session,
        approval_id=approval_id,
    )

    target_status = {
        RecoveryApprovalDecision.APPROVE: RecoveryApprovalStatus.APPROVED,
        RecoveryApprovalDecision.REJECT: RecoveryApprovalStatus.REJECTED,
    }[decision]
    if approval.status == target_status.value:
        if (
            approval.decided_by == normalized_reviewer
            and approval.decision_reason == normalized_reason
        ):
            return RecoveryApprovalDecisionResult(
                approval=approval,
                disposition=RecoveryApprovalDecisionDisposition.ALREADY_DECIDED,
            )
        raise RecoveryApprovalConflictError(
            "Approval was already decided with different evidence",
        )
    if approval.status != RecoveryApprovalStatus.PENDING.value:
        raise RecoveryApprovalConflictError(
            f"Approval cannot be decided from {approval.status}",
        )
    if approval.version != expected_version:
        raise RecoveryApprovalConflictError(
            f"Approval version changed from {expected_version} to {approval.version}",
        )
    if decided_at >= approval.expires_at:
        await _expire_approval(
            session,
            approval=approval,
            action=action,
            recovery_case=recovery_case,
            expired_at=decided_at,
        )
        return RecoveryApprovalDecisionResult(
            approval=approval,
            disposition=RecoveryApprovalDecisionDisposition.EXPIRED,
        )
    if action.status != RecoveryActionStatus.APPROVAL_REQUIRED.value:
        raise RecoveryApprovalStateError(
            f"Recovery action cannot be approved from {action.status}",
        )

    approval.status = target_status.value
    approval.decided_at = decided_at
    approval.decided_by = normalized_reviewer
    approval.decision_reason = normalized_reason
    approval.version += 1

    if decision is RecoveryApprovalDecision.APPROVE:
        if action.execute_after is not None and action.execute_after > decided_at:
            action.status = RecoveryActionStatus.SCHEDULED.value
            recovery_case.next_action_at = action.execute_after
        else:
            action.status = RecoveryActionStatus.ALLOWED.value
            recovery_case.next_action_at = decided_at
        recovery_case.status = RecoveryCaseStatus.READY.value
    else:
        action.status = RecoveryActionStatus.CANCELLED.value
        action.completed_at = decided_at
        recovery_case.status = RecoveryCaseStatus.ESCALATED.value
        recovery_case.next_action_at = None
    recovery_case.version += 1

    await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type=f"approval.{target_status.value}",
            actor_type=RecoveryAuditActor.OPERATOR,
            recovery_action_id=action.id,
            agent_run_id=action.agent_run_id,
            event_data={
                "approval_id": str(approval.id),
                "approval_version": approval.version,
                "reviewer_id": normalized_reviewer,
                "decision_reason": normalized_reason,
            },
            occurred_at=decided_at,
        ),
    )
    return RecoveryApprovalDecisionResult(
        approval=approval,
        disposition=RecoveryApprovalDecisionDisposition.DECIDED,
    )


async def expire_pending_recovery_approvals(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int = 100,
) -> int:
    _require_timezone_aware(reference_time, field_name="Approval expiry time")
    if not 1 <= batch_size <= 500:
        raise ValueError("Approval expiry batch size must be between 1 and 500")

    result = await session.execute(
        select(RecoveryApproval.id)
        .where(
            RecoveryApproval.status == RecoveryApprovalStatus.PENDING.value,
            RecoveryApproval.expires_at <= reference_time,
        )
        .order_by(RecoveryApproval.expires_at, RecoveryApproval.id)
        .with_for_update(skip_locked=True)
        .limit(batch_size),
    )
    approval_ids = tuple(result.scalars().all())
    for approval_id in approval_ids:
        approval, action, recovery_case = await _load_approval_graph_for_update(
            session,
            approval_id=approval_id,
        )
        if approval.status != RecoveryApprovalStatus.PENDING.value:
            continue
        await _expire_approval(
            session,
            approval=approval,
            action=action,
            recovery_case=recovery_case,
            expired_at=reference_time,
        )
    return len(approval_ids)


async def list_recovery_approvals(
    session: AsyncSession,
    *,
    status: RecoveryApprovalStatus | None = None,
    limit: int = 100,
) -> tuple[RecoveryApproval, ...]:
    if not 1 <= limit <= 500:
        raise ValueError("Approval list limit must be between 1 and 500")
    statement = select(RecoveryApproval)
    if status is not None:
        statement = statement.where(RecoveryApproval.status == status.value)
    result = await session.execute(
        statement.order_by(
            RecoveryApproval.requested_at.desc(),
            RecoveryApproval.id,
        ).limit(limit),
    )
    return tuple(result.scalars().all())
