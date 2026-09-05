from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryApproval,
    RecoveryApprovalStatus,
    RecoveryCase,
)
from app.domain.incidents import IncidentSeverity
from app.domain.recovery import RecoveryCaseStatus
from app.services import recovery_approval_service
from app.services.recovery_approval_service import (
    RecoveryApprovalConflictError,
    RecoveryApprovalDecision,
    RecoveryApprovalDecisionDisposition,
    build_recovery_approval_requirement,
    create_recovery_approval_request,
    decide_recovery_approval,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
CASE_ID = UUID("ca000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("ca000000-0000-0000-0000-000000000002")
RUN_ID = UUID("ca000000-0000-0000-0000-000000000003")
APPROVAL_ID = UUID("ca000000-0000-0000-0000-000000000004")


def query_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def build_case() -> RecoveryCase:
    return RecoveryCase(
        id=CASE_ID,
        payment_attempt_id=UUID("ca000000-0000-0000-0000-000000000005"),
        status=RecoveryCaseStatus.AWAITING_APPROVAL.value,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        recovery_attempt_count=0,
        version=1,
        customer_contact_allowed=False,
        opened_at=NOW - timedelta(seconds=10),
    )


def build_action(
    *,
    status: RecoveryActionStatus = RecoveryActionStatus.APPROVAL_REQUIRED,
) -> RecoveryAction:
    return RecoveryAction(
        id=ACTION_ID,
        recovery_case_id=CASE_ID,
        agent_run_id=RUN_ID,
        sequence_number=1,
        idempotency_key="approval-service-test",
        action_type="create_payment_link",
        status=status.value,
        proposal_reason="Create an exact-amount recovery link",
        amount_minor=349_900,
        currency="INR",
        policy_outcome="allow",
        policy_guardrails=[],
        policy_explanation="All deterministic guardrails passed",
        policy_version="deterministic-v1",
        policy_evaluated_at=NOW - timedelta(seconds=2),
        execution_attempt_count=0,
    )


def build_approval(
    *,
    status: RecoveryApprovalStatus = RecoveryApprovalStatus.PENDING,
    version: int = 0,
) -> RecoveryApproval:
    return RecoveryApproval(
        id=APPROVAL_ID,
        recovery_case_id=CASE_ID,
        recovery_action_id=ACTION_ID,
        status=status.value,
        request_reason="amount_requires_operator_approval",
        amount_minor=349_900,
        currency="INR",
        threshold_minor=300_000,
        request_context={},
        requested_at=NOW - timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=13),
        version=version,
    )


def patch_audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    append = AsyncMock()
    monkeypatch.setattr(
        recovery_approval_service,
        "append_recovery_audit_event",
        append,
    )
    return append


@pytest.mark.asyncio
async def test_creates_durable_approval_request_and_blocks_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    recovery_case = build_case()
    recovery_case.status = RecoveryCaseStatus.READY.value
    action = build_action(status=RecoveryActionStatus.ALLOWED)
    append = patch_audit(monkeypatch)

    approval = await create_recovery_approval_request(
        session,
        recovery_case=recovery_case,
        action=action,
        requirement=build_recovery_approval_requirement(
            action,
            threshold_minor=300_000,
        ),
        requested_at=NOW,
        approval_window=timedelta(minutes=15),
    )

    assert approval.status == RecoveryApprovalStatus.PENDING.value
    assert approval.expires_at == NOW + timedelta(minutes=15)
    assert action.status == RecoveryActionStatus.APPROVAL_REQUIRED.value
    session.add.assert_called_once_with(approval)
    session.flush.assert_awaited_once()
    assert append.await_args.kwargs["request"].event_type == "approval.requested"


def test_medium_incident_below_threshold_does_not_enter_amount_review_queue() -> None:
    requirement = build_recovery_approval_requirement(
        build_action(status=RecoveryActionStatus.ALLOWED),
        threshold_minor=1_000_000,
        active_incident_severity=IncidentSeverity.MEDIUM,
    )

    assert requirement is None


def test_near_maximum_attempts_below_threshold_does_not_enter_amount_review_queue() -> None:
    requirement = build_recovery_approval_requirement(
        build_action(status=RecoveryActionStatus.ALLOWED),
        threshold_minor=1_000_000,
        recovery_attempt_count=2,
    )

    assert requirement is None


@pytest.mark.asyncio
async def test_approval_atomically_releases_action_for_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = build_approval()
    action = build_action()
    recovery_case = build_case()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        query_result(approval),
        query_result(action),
        query_result(recovery_case),
    )
    append = patch_audit(monkeypatch)

    result = await decide_recovery_approval(
        session,
        approval_id=APPROVAL_ID,
        decision=RecoveryApprovalDecision.APPROVE,
        reviewer_id="judge-demo-operator",
        reason="Amount and recovery evidence verified",
        expected_version=0,
        decided_at=NOW,
    )

    assert result.disposition is RecoveryApprovalDecisionDisposition.DECIDED
    assert approval.status == RecoveryApprovalStatus.APPROVED.value
    assert approval.version == 1
    assert action.status == RecoveryActionStatus.ALLOWED.value
    assert recovery_case.status == RecoveryCaseStatus.READY.value
    assert recovery_case.next_action_at == NOW
    assert append.await_args.kwargs["request"].event_type == "approval.approved"


@pytest.mark.asyncio
async def test_rejection_cancels_action_and_closes_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = build_approval()
    action = build_action()
    recovery_case = build_case()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        query_result(approval),
        query_result(action),
        query_result(recovery_case),
    )
    append = patch_audit(monkeypatch)

    await decide_recovery_approval(
        session,
        approval_id=APPROVAL_ID,
        decision=RecoveryApprovalDecision.REJECT,
        reviewer_id="merchant-risk-reviewer",
        reason="Customer requested no further recovery",
        expected_version=0,
        decided_at=NOW,
    )

    assert approval.status == RecoveryApprovalStatus.REJECTED.value
    assert action.status == RecoveryActionStatus.CANCELLED.value
    assert recovery_case.status == RecoveryCaseStatus.CANCELLED.value
    assert recovery_case.closed_at == NOW
    assert recovery_case.close_reason == "approval_rejected_without_execution"
    assert append.await_args.kwargs["request"].event_type == "approval.rejected"


@pytest.mark.asyncio
async def test_expired_decision_never_releases_provider_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = build_approval()
    approval.expires_at = NOW
    action = build_action()
    recovery_case = build_case()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        query_result(approval),
        query_result(action),
        query_result(recovery_case),
    )
    append = patch_audit(monkeypatch)

    result = await decide_recovery_approval(
        session,
        approval_id=APPROVAL_ID,
        decision=RecoveryApprovalDecision.APPROVE,
        reviewer_id="late-reviewer",
        reason="Attempted after expiry",
        expected_version=0,
        decided_at=NOW,
    )

    assert result.disposition is RecoveryApprovalDecisionDisposition.EXPIRED
    assert approval.status == RecoveryApprovalStatus.EXPIRED.value
    assert action.status == RecoveryActionStatus.CANCELLED.value
    assert recovery_case.status == RecoveryCaseStatus.CANCELLED.value
    assert recovery_case.closed_at == NOW
    assert recovery_case.close_reason == "approval_expired_without_execution"
    assert append.await_args.kwargs["request"].event_type == "approval.expired"


@pytest.mark.asyncio
async def test_stale_version_is_rejected_without_mutation() -> None:
    approval = build_approval(version=1)
    action = build_action()
    recovery_case = build_case()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        query_result(approval),
        query_result(action),
        query_result(recovery_case),
    )

    with pytest.raises(RecoveryApprovalConflictError, match="version changed"):
        await decide_recovery_approval(
            session,
            approval_id=APPROVAL_ID,
            decision=RecoveryApprovalDecision.APPROVE,
            reviewer_id="reviewer-a",
            reason="Evidence verified",
            expected_version=0,
            decided_at=NOW,
        )

    assert approval.status == RecoveryApprovalStatus.PENDING.value
    assert action.status == RecoveryActionStatus.APPROVAL_REQUIRED.value


@pytest.mark.asyncio
async def test_identical_decision_replay_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = build_approval(status=RecoveryApprovalStatus.APPROVED, version=1)
    approval.decided_by = "reviewer-a"
    approval.decision_reason = "Evidence verified"
    approval.decided_at = NOW - timedelta(seconds=1)
    action = build_action(status=RecoveryActionStatus.ALLOWED)
    recovery_case = build_case()
    recovery_case.status = RecoveryCaseStatus.READY.value
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        query_result(approval),
        query_result(action),
        query_result(recovery_case),
    )
    append = patch_audit(monkeypatch)

    result = await decide_recovery_approval(
        session,
        approval_id=APPROVAL_ID,
        decision=RecoveryApprovalDecision.APPROVE,
        reviewer_id="reviewer-a",
        reason="Evidence verified",
        expected_version=0,
        decided_at=NOW,
    )

    assert result.disposition is RecoveryApprovalDecisionDisposition.ALREADY_DECIDED
    assert approval.version == 1
    append.assert_not_awaited()
