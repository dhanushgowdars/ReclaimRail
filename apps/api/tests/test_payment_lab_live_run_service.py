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


def build_payment() -> MagicMock:
    payment = MagicMock(spec=PaymentAttempt)
    payment.id = ATTEMPT_ID
    payment.provider_payment_id = "pay_live_status"
    payment.current_state = "failed"
    payment.error_code = "BAD_REQUEST_ERROR"
    payment.error_reason = "payment_failed"
    payment.state_event_created_at = NOW + timedelta(seconds=5)
    return payment


def build_case(*, status: str = "ready") -> MagicMock:
    recovery_case = MagicMock(spec=RecoveryCase)
    recovery_case.id = CASE_ID
    recovery_case.status = status
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
    action.provider_action_id = "plink_live_status"
    action.provider_action_status = "created"
    action.provider_action_url = "https://rzp.io/i/live-status"
    action.provider_action_expires_at = NOW + timedelta(hours=24)
    action.completed_at = NOW + timedelta(seconds=8)
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
    assert result.terminal is False
    assert result.poll_after_milliseconds == 1000
    assert result.payment is None
    assert result.agent is None
    assert result.actions == ()
    assert result.outcome is None
    assert [step.status for step in result.steps] == [
        PaymentLabLiveStepStatus.COMPLETED,
        PaymentLabLiveStepStatus.ACTIVE,
        PaymentLabLiveStepStatus.PENDING,
        PaymentLabLiveStepStatus.PENDING,
    ]
    session.execute.assert_not_awaited()


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
    assert result.terminal is True
    assert result.poll_after_milliseconds is None
    assert result.payment is not None
    assert result.payment.provider_payment_id == "pay_live_status"
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
    assert result.terminal is True
    assert result.poll_after_milliseconds is None
    assert result.outcome is None
    assert result.agent is not None
    assert result.agent.recovery_case_status == "escalated"
    assert result.actions[0].policy_outcome == "escalate"
    assert result.steps[-1].label == "Safe disposition"
    assert result.steps[-1].status is PaymentLabLiveStepStatus.COMPLETED
    assert result.steps[-1].detail == ("Policy required human review; no financial action executed")


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
