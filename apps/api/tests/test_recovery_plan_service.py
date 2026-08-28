from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import RevenueIncident, RevenueIncidentStatus
from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryActionStatus,
    RecoveryAgentRunStatus,
    RecoveryApprovalStatus,
    RecoveryAuditEvent,
    RecoveryCase,
    RecoveryPlannerProvider,
)
from app.domain.recovery import RecoveryCaseStatus, RecoveryChannel, RecoveryPlanDecision
from app.services import recovery_approval_service, recovery_plan_service
from app.services.recovery_plan_service import (
    RecoveryCaseNotPlannableError,
    RecoveryPlanningCaseNotFoundError,
    RecoveryPlanningPaymentNotFoundError,
    plan_and_persist_recovery_case,
)

NOW = datetime(2026, 8, 25, 11, 0, tzinfo=UTC)
CASE_ID = UUID("81000000-0000-0000-0000-000000000001")
PAYMENT_ID = UUID("81000000-0000-0000-0000-000000000002")
INCIDENT_ID = UUID("81000000-0000-0000-0000-000000000003")


def query_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def create_case(
    *,
    status: RecoveryCaseStatus = RecoveryCaseStatus.OPEN,
    source_incident_id: UUID | None = None,
    last_customer_contact_at: datetime | None = None,
) -> RecoveryCase:
    return RecoveryCase(
        id=CASE_ID,
        payment_attempt_id=PAYMENT_ID,
        source_incident_id=source_incident_id,
        status=status.value,
        amount_minor=250_000,
        currency="INR",
        payment_method="upi",
        recovery_attempt_count=0,
        version=0,
        customer_contact_allowed=True,
        last_customer_contact_at=last_customer_contact_at,
        opened_at=NOW - timedelta(minutes=10),
    )


def create_payment(*, state: str = "failed") -> PaymentAttempt:
    return PaymentAttempt(
        id=PAYMENT_ID,
        provider="razorpay",
        provider_payment_id="pay_recovery_plan_test",
        amount_minor=250_000,
        currency="INR",
        method="upi",
        payment_created_at=NOW - timedelta(minutes=11),
        current_state=state,
        state_version=1,
        state_provider_event_id="evt_recovery_plan_test",
        state_webhook_event_id=UUID("81000000-0000-0000-0000-000000000004"),
        state_event_created_at=NOW - timedelta(minutes=10),
        error_code="BAD_REQUEST_ERROR",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=(state == "failed"),
        late_authorization_detected_at=(NOW if state == "authorized" else None),
    )


def create_audit_event() -> RecoveryAuditEvent:
    return RecoveryAuditEvent(
        id=UUID("81000000-0000-0000-0000-000000000005"),
        recovery_case_id=CASE_ID,
        sequence_number=2,
        event_type="agent.plan.persisted",
        actor_type="agent",
        event_data={},
        previous_event_hash="a" * 64,
        event_hash="b" * 64,
        occurred_at=NOW,
    )


def create_session(
    *,
    recovery_case: RecoveryCase | None,
    payment: PaymentAttempt | None,
    previous_run_number: int = 0,
    incident: RevenueIncident | None = None,
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    results = [query_result(recovery_case)]
    if recovery_case is not None and recovery_case.status in {
        RecoveryCaseStatus.OPEN.value,
        RecoveryCaseStatus.WAITING.value,
    }:
        results.append(query_result(payment))
        results.append(query_result(incident))
        if payment is not None:
            results.append(query_result(previous_run_number))
    session.execute.side_effect = results
    return session


def patch_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AsyncMock, RecoveryAuditEvent]:
    audit_event = create_audit_event()
    append_audit = AsyncMock(return_value=audit_event)
    monkeypatch.setattr(
        recovery_plan_service,
        "append_recovery_audit_event",
        append_audit,
    )
    return append_audit, audit_event


@pytest.mark.asyncio
async def test_persists_policy_evaluated_recovery_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case()
    session = create_session(
        recovery_case=recovery_case,
        payment=create_payment(),
    )
    append_audit, audit_event = patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )

    assert result.plan.decision is RecoveryPlanDecision.RECOVER
    assert result.agent_run.status == RecoveryAgentRunStatus.SUCCEEDED.value
    assert result.agent_run.planner_provider == RecoveryPlannerProvider.DETERMINISTIC.value
    assert result.agent_run.run_number == 1
    assert result.agent_run.proposed_action_count == 3
    assert result.audit_event is audit_event
    assert [action.sequence_number for action in result.actions] == [1, 2, 3]
    assert [action.status for action in result.actions] == [
        RecoveryActionStatus.ALLOWED.value,
        RecoveryActionStatus.ALLOWED.value,
        RecoveryActionStatus.ALLOWED.value,
    ]
    assert recovery_case.status == RecoveryCaseStatus.READY.value
    assert recovery_case.next_action_at == NOW
    assert recovery_case.version == 1
    assert session.add.call_count == 4
    assert session.flush.await_count == 2
    append_audit.assert_awaited_once()
    audit_request = append_audit.await_args.kwargs["request"]
    assert audit_request.event_type == "agent.plan.persisted"
    assert audit_request.agent_run_id == result.agent_run.id
    assert len(audit_request.event_data["actions"]) == 3


@pytest.mark.asyncio
async def test_high_value_payment_link_waits_for_human_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case()
    session = create_session(
        recovery_case=recovery_case,
        payment=create_payment(),
    )
    append_audit, _ = patch_audit(monkeypatch)
    monkeypatch.setattr(
        recovery_approval_service,
        "append_recovery_audit_event",
        append_audit,
    )

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
        approval_threshold_minor=200_000,
        approval_window=timedelta(minutes=15),
    )

    payment_link_action = result.actions[0]
    assert payment_link_action.action_type == "create_payment_link"
    assert payment_link_action.status == RecoveryActionStatus.APPROVAL_REQUIRED.value
    assert recovery_case.status == RecoveryCaseStatus.AWAITING_APPROVAL.value
    assert recovery_case.next_action_at is None
    assert len(result.approvals) == 1
    approval = result.approvals[0]
    assert approval.recovery_action_id == payment_link_action.id
    assert approval.status == RecoveryApprovalStatus.PENDING.value
    assert approval.amount_minor == 250_000
    assert approval.threshold_minor == 200_000
    assert approval.expires_at == NOW + timedelta(minutes=15)
    assert append_audit.await_count == 2
    assert [call.kwargs["request"].event_type for call in append_audit.await_args_list] == [
        "agent.plan.persisted",
        "approval.requested",
    ]


@pytest.mark.asyncio
async def test_policy_blocks_contact_actions_during_quiet_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case(
        last_customer_contact_at=NOW - timedelta(minutes=30),
    )
    session = create_session(
        recovery_case=recovery_case,
        payment=create_payment(),
    )
    patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )

    assert [action.status for action in result.actions] == [
        RecoveryActionStatus.ALLOWED.value,
        RecoveryActionStatus.BLOCKED.value,
        RecoveryActionStatus.BLOCKED.value,
    ]
    assert result.actions[1].policy_guardrails == ["quiet_period_active"]
    assert recovery_case.status == RecoveryCaseStatus.READY.value


@pytest.mark.asyncio
async def test_active_high_incident_schedules_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case(source_incident_id=INCIDENT_ID)
    incident = MagicMock(spec=RevenueIncident)
    incident.id = INCIDENT_ID
    incident.status = RevenueIncidentStatus.OPEN.value
    incident.severity = "high"
    incident.scope = "payment_method"
    incident.dimension_value = "upi"
    session = create_session(
        recovery_case=recovery_case,
        payment=create_payment(),
        incident=incident,
    )
    patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )

    assert result.plan.decision is RecoveryPlanDecision.WAIT
    assert len(result.actions) == 1
    assert result.actions[0].status == RecoveryActionStatus.SCHEDULED.value
    assert recovery_case.status == RecoveryCaseStatus.WAITING.value
    assert recovery_case.next_action_at == NOW + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_new_matching_incident_blocks_recovery_without_source_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case()
    incident = MagicMock(spec=RevenueIncident)
    incident.id = INCIDENT_ID
    incident.status = RevenueIncidentStatus.OPEN.value
    incident.severity = "critical"
    incident.scope = "payment_method"
    incident.dimension_value = "upi"
    session = create_session(
        recovery_case=recovery_case,
        payment=create_payment(),
        incident=incident,
    )
    patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )

    assert result.plan.decision is RecoveryPlanDecision.WAIT
    assert result.agent_run.input_snapshot["active_incident"] == {
        "incident_id": str(INCIDENT_ID),
        "scope": "payment_method",
        "dimension_value": "upi",
        "severity": "critical",
    }


@pytest.mark.asyncio
async def test_late_authorization_stops_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case()
    session = create_session(
        recovery_case=recovery_case,
        payment=create_payment(state="authorized"),
    )
    patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )

    assert result.plan.decision is RecoveryPlanDecision.STOP
    assert result.actions[0].status == RecoveryActionStatus.STOPPED.value
    assert recovery_case.status == RecoveryCaseStatus.CANCELLED.value
    assert recovery_case.closed_at == NOW
    assert recovery_case.close_reason == "bounded_plan_stop"


@pytest.mark.asyncio
async def test_assigns_next_run_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = create_session(
        recovery_case=create_case(),
        payment=create_payment(),
        previous_run_number=2,
    )
    patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(),
        alternate_payment_methods=(),
        planned_at=NOW,
    )

    assert result.agent_run.run_number == 3


@pytest.mark.asyncio
async def test_missing_case_is_rejected_before_persistence() -> None:
    session = create_session(
        recovery_case=None,
        payment=None,
    )

    with pytest.raises(RecoveryPlanningCaseNotFoundError, match=str(CASE_ID)):
        await plan_and_persist_recovery_case(
            session,
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=NOW,
        )

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_nonplannable_case_is_rejected() -> None:
    session = create_session(
        recovery_case=create_case(status=RecoveryCaseStatus.READY),
        payment=create_payment(),
    )

    with pytest.raises(RecoveryCaseNotPlannableError, match="ready"):
        await plan_and_persist_recovery_case(
            session,
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=NOW,
        )

    assert session.execute.await_count == 1
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_missing_payment_is_rejected() -> None:
    session = create_session(
        recovery_case=create_case(),
        payment=None,
    )

    with pytest.raises(RecoveryPlanningPaymentNotFoundError, match=str(PAYMENT_ID)):
        await plan_and_persist_recovery_case(
            session,
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=NOW,
        )

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_rejects_naive_planning_time_before_database_access() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="timezone-aware"):
        await plan_and_persist_recovery_case(
            session,
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=datetime(2026, 8, 25, 11, 0),
        )

    session.execute.assert_not_awaited()
