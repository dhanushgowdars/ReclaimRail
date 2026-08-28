from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import RecoveryAction, RecoveryAgentRun, RecoveryCase
from app.db.models.recovery_outcome import RecoveryOutcome
from app.services.payment_lab_live_run_service import (
    PaymentLabLiveBusinessState,
    PaymentLabLiveRunNotFoundError,
    PaymentLabLiveStage,
    PaymentLabLiveStepStatus,
    load_payment_lab_live_run,
)

NOW = datetime(2026, 8, 26, 19, 0, tzinfo=UTC)
RUN_ID = UUID("93000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("93000000-0000-0000-0000-000000000002")
ATTEMPT_ID = UUID("93000000-0000-0000-0000-000000000003")
CASE_ID = UUID("93000000-0000-0000-0000-000000000004")
AGENT_ID = UUID("93000000-0000-0000-0000-000000000005")
ACTION_ID = UUID("93000000-0000-0000-0000-000000000006")
OUTCOME_ID = UUID("93000000-0000-0000-0000-000000000007")


def scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def build_run(*, status: str = PaymentLabRunStatus.CHECKOUT_READY.value) -> MagicMock:
    run = MagicMock(spec=PaymentLabRun)
    run.id = RUN_ID
    run.client_request_id = CLIENT_ID
    run.mode = "guided"
    run.provenance = "razorpay_test"
    run.status = status
    run.amount_minor = 349_900
    run.currency = "INR"
    run.payment_method = "netbanking"
    run.provider_order_id = "order_live_status"
    run.provider_order_status = "created"
    run.provider_created_at = NOW
    run.payment_attempt_id = None
    run.failure_code = None
    run.checkout_expires_at = NOW + timedelta(minutes=10)
    run.created_at = NOW
    run.updated_at = NOW
    return run


def build_payment(*, state: str = "failed") -> MagicMock:
    payment = MagicMock(spec=PaymentAttempt)
    payment.id = ATTEMPT_ID
    payment.provider_payment_id = "pay_live_status"
    payment.method = "netbanking"
    payment.current_state = state
    payment.error_code = "BAD_REQUEST_ERROR" if state == "failed" else None
    payment.error_reason = "payment_failed" if state == "failed" else None
    payment.state_event_created_at = NOW + timedelta(seconds=5)
    return payment


def build_case(*, status: str = "ready") -> MagicMock:
    recovery_case = MagicMock(spec=RecoveryCase)
    recovery_case.id = CASE_ID
    recovery_case.status = status
    recovery_case.opened_at = NOW + timedelta(seconds=5, milliseconds=200)
    return recovery_case


def build_agent(*, fallback_used: bool = False) -> MagicMock:
    agent = MagicMock(spec=RecoveryAgentRun)
    agent.id = AGENT_ID
    agent.status = "succeeded"
    agent.planner_provider = "gemini" if not fallback_used else "deterministic"
    agent.model_name = "gemini-3.6-flash" if not fallback_used else None
    agent.evidence = {
        "fallback_used": fallback_used,
        "fallback_reason": "provider_failure" if fallback_used else None,
    }
    agent.reasoning_summary = "Offer a bounded alternate payment path"
    agent.proposed_action_count = 1
    agent.started_at = NOW + timedelta(seconds=6)
    agent.completed_at = NOW + timedelta(seconds=7)
    return agent


def build_action() -> MagicMock:
    action = MagicMock(spec=RecoveryAction)
    action.id = ACTION_ID
    action.sequence_number = 1
    action.action_type = "create_payment_link"
    action.status = "succeeded"
    action.policy_outcome = "allow"
    action.policy_guardrails = []
    action.policy_explanation = "All deterministic checks passed"
    action.policy_evaluated_at = NOW + timedelta(seconds=7, milliseconds=200)
    action.provider_action_id = "plink_live_status"
    action.provider_action_status = "created"
    action.provider_action_url = "https://rzp.io/i/live-status"
    action.provider_action_expires_at = NOW + timedelta(hours=24)
    action.started_at = NOW + timedelta(seconds=7, milliseconds=500)
    action.completed_at = NOW + timedelta(seconds=8)
    action.created_at = NOW + timedelta(seconds=7)
    return action


def build_escalated_action() -> MagicMock:
    action = build_action()
    action.action_type = "create_payment_link"
    action.status = "escalated"
    action.policy_outcome = "escalate"
    action.policy_guardrails = ["automatic_amount_limit"]
    action.policy_explanation = "Automatic amount limit requires human review"
    action.provider_action_id = None
    action.provider_action_status = None
    action.provider_action_url = None
    action.provider_action_expires_at = None
    return action


def build_outcome() -> MagicMock:
    outcome = MagicMock(spec=RecoveryOutcome)
    outcome.id = OUTCOME_ID
    outcome.status = "recovered"
    outcome.attribution = "direct_payment_link"
    outcome.gross_recovered_minor = 349_900
    outcome.duplicate_collection_prevented_minor = 0
    outcome.evidence_event_ids = ["evt_paid", "evt_captured"]
    outcome.occurred_at = NOW + timedelta(seconds=10)
    return outcome


@pytest.mark.asyncio
async def test_checkout_run_waits_for_signed_failure() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = build_run()

    result = await load_payment_lab_live_run(
        session,
        payment_lab_run_id=RUN_ID,
    )

    assert result.current_stage is PaymentLabLiveStage.CHECKOUT
    assert result.business_state is (PaymentLabLiveBusinessState.AWAITING_ORIGINAL_PAYMENT)
    assert result.active_step_key == "verified_failure"
    assert result.automation_complete is False
    assert result.financial_outcome_terminal is False
    assert result.terminal is False
    assert result.poll_after_milliseconds == 500
    assert result.payment is None
    assert result.agent is None
    assert result.actions == ()
    assert result.outcome is None
    assert [step.status for step in result.steps] == [
        PaymentLabLiveStepStatus.COMPLETED,
        PaymentLabLiveStepStatus.ACTIVE,
        PaymentLabLiveStepStatus.PENDING,
        PaymentLabLiveStepStatus.PENDING,
        PaymentLabLiveStepStatus.PENDING,
        PaymentLabLiveStepStatus.PENDING,
        PaymentLabLiveStepStatus.PENDING,
    ]
    assert [step.key for step in result.steps] == [
        "payment_attempt",
        "verified_failure",
        "recovery_case",
        "agent_recommendation",
        "policy_decision",
        "provider_action",
        "measured_outcome",
    ]
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_failure_exposes_real_stabilization_state() -> None:
    run = build_run(status=PaymentLabRunStatus.PAYMENT_ATTEMPTED.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment()
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.return_value = scalar_result(None)

    result = await load_payment_lab_live_run(session, payment_lab_run_id=RUN_ID)

    assert result.current_stage is PaymentLabLiveStage.FAILURE
    assert result.business_state is PaymentLabLiveBusinessState.FAILURE_STABILIZING
    assert result.active_step_key == "recovery_case"
    assert result.waiting_reason == "Five-second late-authorization safety window"
    assert result.steps[1].status is PaymentLabLiveStepStatus.COMPLETED
    assert result.steps[2].status is PaymentLabLiveStepStatus.ACTIVE
    assert result.steps[2].detail == (
        "Five-second signed-evidence stabilization window before recovery begins"
    )
    assert all(step.status is PaymentLabLiveStepStatus.PENDING for step in result.steps[3:])


@pytest.mark.asyncio
async def test_completed_run_exposes_provider_agent_policy_and_outcome_evidence() -> None:
    run = build_run(status=PaymentLabRunStatus.RECOVERY_RUNNING.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment()
    recovery_case = build_case()
    agent = build_agent()
    action = build_action()
    outcome = build_outcome()

    action_result = MagicMock()
    action_result.scalars.return_value.all.return_value = [action]
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.side_effect = (
        scalar_result(recovery_case),
        scalar_result(agent),
        action_result,
        scalar_result(outcome),
    )

    result = await load_payment_lab_live_run(
        session,
        payment_lab_run_id=RUN_ID,
    )

    assert result.current_stage is PaymentLabLiveStage.COMPLETED
    assert result.business_state is PaymentLabLiveBusinessState.RECOVERED
    assert result.terminal is True
    assert result.poll_after_milliseconds is None
    assert result.payment is not None
    assert result.payment.provider_payment_id == "pay_live_status"
    assert result.payment_method == "netbanking"
    assert result.agent is not None
    assert result.agent.planner_provider == "gemini"
    assert result.agent.fallback_used is False
    assert result.actions[0].policy_outcome == "allow"
    assert result.actions[0].provider_action_id == "plink_live_status"
    assert result.actions[0].provider_action_url == "https://rzp.io/i/live-status"
    assert result.actions[0].provider_action_expires_at == NOW + timedelta(hours=24)
    assert result.outcome is not None
    assert result.outcome.gross_recovered_minor == 349_900
    assert result.outcome.evidence_event_count == 2
    assert all(step.status is PaymentLabLiveStepStatus.COMPLETED for step in result.steps)


@pytest.mark.asyncio
async def test_created_payment_link_waits_for_provider_outcome() -> None:
    run = build_run(status=PaymentLabRunStatus.RECOVERY_RUNNING.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment()
    recovery_case = build_case()
    agent = build_agent()
    action = build_action()

    action_result = MagicMock()
    action_result.scalars.return_value.all.return_value = [action]
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.side_effect = (
        scalar_result(recovery_case),
        scalar_result(agent),
        action_result,
        scalar_result(None),
    )

    result = await load_payment_lab_live_run(session, payment_lab_run_id=RUN_ID)

    assert result.current_stage is PaymentLabLiveStage.OUTCOME
    assert result.business_state is (PaymentLabLiveBusinessState.AWAITING_RECOVERY_PAYMENT)
    assert result.automation_complete is True
    assert result.financial_outcome_terminal is False
    assert result.terminal is False
    assert result.outcome is None
    assert result.steps[-2].status is PaymentLabLiveStepStatus.COMPLETED
    assert result.steps[-1].status is PaymentLabLiveStepStatus.ACTIVE
    assert result.steps[-1].detail == "Waiting for provider reconciliation"


@pytest.mark.asyncio
async def test_policy_escalation_is_a_terminal_safe_disposition() -> None:
    run = build_run(status=PaymentLabRunStatus.RECOVERY_RUNNING.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment()
    recovery_case = build_case(status="escalated")
    agent = build_agent()
    action = build_escalated_action()

    action_result = MagicMock()
    action_result.scalars.return_value.all.return_value = [action]
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.side_effect = (
        scalar_result(recovery_case),
        scalar_result(agent),
        action_result,
        scalar_result(None),
    )

    result = await load_payment_lab_live_run(
        session,
        payment_lab_run_id=RUN_ID,
    )

    assert result.current_stage is PaymentLabLiveStage.COMPLETED
    assert result.business_state is PaymentLabLiveBusinessState.ESCALATED
    assert result.terminal is True
    assert result.poll_after_milliseconds is None
    assert result.outcome is None
    assert result.agent is not None
    assert result.agent.recovery_case_status == "escalated"
    assert result.actions[0].policy_outcome == "escalate"
    assert result.steps[-2].label == "Safe disposition"
    assert result.steps[-1].status is PaymentLabLiveStepStatus.COMPLETED
    assert result.steps[-1].detail == ("Policy required human review; no financial action executed")


@pytest.mark.asyncio
async def test_successful_original_payment_never_enters_failure_or_recovery() -> None:
    run = build_run(status=PaymentLabRunStatus.COMPLETED.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment(state="captured")
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.return_value = scalar_result(None)

    result = await load_payment_lab_live_run(session, payment_lab_run_id=RUN_ID)

    assert result.business_state is (PaymentLabLiveBusinessState.ORIGINAL_PAYMENT_SUCCEEDED)
    assert result.current_stage is PaymentLabLiveStage.COMPLETED
    assert result.state_label == "Original payment completed; no recovery required"
    assert result.terminal is True
    assert result.automation_complete is True
    assert result.financial_outcome_terminal is True
    assert result.active_step_key is None
    assert result.waiting_reason is None
    assert [step.key for step in result.steps] == ["payment_attempt"]
    assert result.steps[0].label == "Original payment"
    assert "failure" not in result.steps[0].detail.casefold()
    assert result.agent is None
    assert result.actions == ()
    assert result.outcome is None


@pytest.mark.asyncio
async def test_late_authorization_remains_live_until_compensation_finishes() -> None:
    run = build_run(status=PaymentLabRunStatus.COMPLETED.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment(state="authorized")
    recovery_case = build_case(status="ready")
    agent = build_agent()
    action = build_action()

    action_result = MagicMock()
    action_result.scalars.return_value.all.return_value = [action]
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.side_effect = (
        scalar_result(recovery_case),
        scalar_result(agent),
        action_result,
        scalar_result(None),
    )

    result = await load_payment_lab_live_run(session, payment_lab_run_id=RUN_ID)

    assert result.business_state is PaymentLabLiveBusinessState.STOPPING_RECOVERY
    assert result.current_stage is PaymentLabLiveStage.OUTCOME
    assert result.terminal is False
    assert result.automation_complete is False
    assert result.financial_outcome_terminal is False
    assert result.active_step_key == "provider_action"
    assert result.waiting_reason == "Waiting for late-authorization compensation"


@pytest.mark.asyncio
async def test_late_authorization_becomes_terminal_after_recovery_is_cancelled() -> None:
    run = build_run(status=PaymentLabRunStatus.COMPLETED.value)
    run.payment_attempt_id = ATTEMPT_ID
    payment = build_payment(state="captured")
    recovery_case = build_case(status="cancelled")
    agent = build_agent()
    action = build_action()

    action_result = MagicMock()
    action_result.scalars.return_value.all.return_value = [action]
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (run, payment)
    session.execute.side_effect = (
        scalar_result(recovery_case),
        scalar_result(agent),
        action_result,
        scalar_result(None),
    )

    result = await load_payment_lab_live_run(session, payment_lab_run_id=RUN_ID)

    assert result.business_state is PaymentLabLiveBusinessState.STOPPED
    assert result.state_label == "Original payment completed; recovery stopped safely"
    assert result.current_stage is PaymentLabLiveStage.COMPLETED
    assert result.terminal is True
    assert result.automation_complete is True
    assert result.financial_outcome_terminal is True
    assert result.active_step_key is None
    assert result.poll_after_milliseconds is None


@pytest.mark.asyncio
async def test_missing_run_is_rejected() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = None

    with pytest.raises(PaymentLabLiveRunNotFoundError):
        await load_payment_lab_live_run(
            session,
            payment_lab_run_id=RUN_ID,
        )

    session.execute.assert_not_awaited()
