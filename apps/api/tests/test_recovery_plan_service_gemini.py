from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import RecoveryActionStatus, RecoveryAuditEvent, RecoveryCase
from app.domain.recovery import (
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlan,
    RecoveryPlanDecision,
)
from app.integrations.gemini import (
    BoundedRecoveryPlannerResult,
    GeminiPlannerFallbackReason,
    GeminiRecoveryAnalysisPayload,
    RecoveryPlannerSource,
)
from app.integrations.gemini.recovery_planner import (
    GeminiRecoveryAlternativePayload,
    GeminiRecoveryObservationPayload,
    GeminiRecoveryReasoningItemPayload,
)
from app.services import recovery_plan_service
from app.services.recovery_plan_service import (
    RecoveryPlannerResultMismatchError,
    load_recovery_planning_context,
    plan_and_persist_recovery_case,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
CASE_ID = UUID("82000000-0000-0000-0000-000000000001")
PAYMENT_ID = UUID("82000000-0000-0000-0000-000000000002")


def query_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def create_case() -> RecoveryCase:
    return RecoveryCase(
        id=CASE_ID,
        payment_attempt_id=PAYMENT_ID,
        status=RecoveryCaseStatus.OPEN.value,
        amount_minor=75_000,
        currency="INR",
        payment_method="upi",
        recovery_attempt_count=0,
        version=0,
        customer_contact_allowed=True,
        opened_at=NOW - timedelta(minutes=10),
    )


def create_payment(*, state: str = "failed") -> PaymentAttempt:
    return PaymentAttempt(
        id=PAYMENT_ID,
        provider="razorpay",
        provider_payment_id="pay_gemini_persistence_test",
        amount_minor=75_000,
        currency="INR",
        method="upi",
        payment_created_at=NOW - timedelta(minutes=11),
        current_state=state,
        state_version=2,
        state_provider_event_id="evt_gemini_persistence_test",
        state_webhook_event_id=UUID("82000000-0000-0000-0000-000000000003"),
        state_event_created_at=NOW - timedelta(minutes=10),
        error_code="BAD_REQUEST_ERROR",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=(state == "failed"),
        late_authorization_detected_at=(NOW if state == "authorized" else None),
    )


def planner_result(
    *,
    source: RecoveryPlannerSource = RecoveryPlannerSource.GEMINI,
    generated_at: datetime = NOW,
    confidence: float | None = None,
) -> BoundedRecoveryPlannerResult:
    plan = RecoveryPlan(
        decision=RecoveryPlanDecision.RECOVER,
        reasoning_summary="Create one bounded payment link from verified evidence",
        proposals=(
            RecoveryActionProposal(
                action_type=RecoveryActionType.CREATE_PAYMENT_LINK,
                reason="Offer a safe retry for the original amount",
                amount_minor=75_000,
                currency="INR",
            ),
        ),
        evidence_codes=("payment_state:failed",),
        generated_at=generated_at,
        planner_version=(
            "gemini-structured-v1" if source is RecoveryPlannerSource.GEMINI else "deterministic-v1"
        ),
    )
    if source is RecoveryPlannerSource.GEMINI:
        return BoundedRecoveryPlannerResult(
            plan=plan,
            source=source,
            model_name="gemini-3.7-flash",
            fallback_used=False,
            fallback_reason=None,
            input_token_count=321,
            output_token_count=87,
            analysis=(
                GeminiRecoveryAnalysisPayload(
                    root_cause_category="customer_authentication_failure",
                    recoverability_assessment="Eligible for one bounded recovery action",
                    confidence=confidence,
                    allowed_action_recommendation="create_payment_link",
                    evidence_references=(
                        "payment_state_snapshot",
                        "merchant_recovery_policy",
                    ),
                    operator_explanation=(
                        "Verified failure remains eligible under the merchant recovery policy."
                    ),
                    observations=(
                        GeminiRecoveryObservationPayload(
                            evidence_reference="payment_state_snapshot",
                        ),
                    ),
                    reasoning_items=(
                        GeminiRecoveryReasoningItemPayload(
                            evidence_references=("payment_state_snapshot",),
                            interpretation="The recorded payment is failed and recoverable.",
                            action_impact="A bounded recovery action may be proposed.",
                        ),
                    ),
                    alternatives_considered=(
                        GeminiRecoveryAlternativePayload(
                            action_type=RecoveryActionType.SEND_RECOVERY_MESSAGE,
                            disposition="not_selected",
                            reason="The payment-link action is the recorded primary proposal.",
                            evidence_references=("merchant_recovery_policy",),
                        ),
                    ),
                    known_uncertainties=(),
                )
                if confidence is not None
                else None
            ),
        )
    return BoundedRecoveryPlannerResult(
        plan=plan,
        source=source,
        model_name=None,
        fallback_used=True,
        fallback_reason=GeminiPlannerFallbackReason.PROVIDER_ERROR,
    )


def create_audit_event() -> RecoveryAuditEvent:
    return RecoveryAuditEvent(
        id=UUID("82000000-0000-0000-0000-000000000004"),
        recovery_case_id=CASE_ID,
        sequence_number=2,
        event_type="agent.plan.persisted",
        actor_type="agent",
        event_data={},
        previous_event_hash="a" * 64,
        event_hash="b" * 64,
        occurred_at=NOW,
    )


def patch_audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    append_audit = AsyncMock(return_value=create_audit_event())
    monkeypatch.setattr(
        recovery_plan_service,
        "append_recovery_audit_event",
        append_audit,
    )
    return append_audit


@pytest.mark.asyncio
async def test_loads_unlocked_context_for_external_planning() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(create_case()),
        query_result(create_payment()),
        query_result(None),
    ]

    context = await load_recovery_planning_context(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )

    assert context.case.case_id == CASE_ID
    assert context.available_channels == (RecoveryChannel.EMAIL,)
    assert context.alternate_payment_methods == ("card",)
    assert all(
        "FOR UPDATE" not in str(call.args[0]).upper() for call in session.execute.await_args_list
    )


@pytest.mark.asyncio
async def test_persists_gemini_metadata_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    recovery_case = create_case()
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(create_payment()),
        query_result(None),
        query_result(0),
    ]
    append_audit = patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
        planner_result=planner_result(confidence=0.91),
    )

    assert result.agent_run.planner_provider == "gemini"
    assert result.agent_run.model_name == "gemini-3.7-flash"
    assert result.agent_run.input_token_count == 321
    assert result.agent_run.output_token_count == 87
    assert result.agent_run.evidence["planner"] == {
        "source": "gemini",
        "model_name": "gemini-3.7-flash",
        "fallback_used": False,
        "fallback_reason": None,
        "input_token_count": 321,
        "output_token_count": 87,
    }
    assert result.agent_run.evidence["bounded_ai_analysis"] == {
        "root_cause_category": "customer_authentication_failure",
        "recoverability_assessment": "Eligible for one bounded recovery action",
        "confidence": 0.91,
        "allowed_action_recommendation": "create_payment_link",
        "evidence_references": [
            "payment_state_snapshot",
            "merchant_recovery_policy",
        ],
        "operator_explanation": (
            "Verified failure remains eligible under the merchant recovery policy."
        ),
        "observations": [{"evidence_reference": "payment_state_snapshot"}],
        "reasoning_items": [
            {
                "evidence_references": ["payment_state_snapshot"],
                "interpretation": "The recorded payment is failed and recoverable.",
                "action_impact": "A bounded recovery action may be proposed.",
            }
        ],
        "alternatives_considered": [
            {
                "action_type": "send_recovery_message",
                "disposition": "not_selected",
                "reason": "The payment-link action is the recorded primary proposal.",
                "evidence_references": ["merchant_recovery_policy"],
            }
        ],
        "known_uncertainties": [],
    }
    assert set(result.agent_run.evidence["bounded_ai_evidence_tools"]) == {
        "payment_state_snapshot",
        "attempt_and_recovery_history",
        "payment_rail_incident_context",
        "merchant_recovery_policy",
    }
    audit_data = append_audit.await_args.kwargs["request"].event_data
    assert audit_data["model_name"] == "gemini-3.7-flash"
    assert audit_data["input_token_count"] == 321
    assert audit_data["bounded_ai_analysis"] == {
        "root_cause_category": "customer_authentication_failure",
        "confidence": 0.91,
        "evidence_references": [
            "payment_state_snapshot",
            "merchant_recovery_policy",
        ],
    }
    assert recovery_case.status == RecoveryCaseStatus.READY.value


@pytest.mark.asyncio
async def test_low_confidence_gemini_plan_does_not_control_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    recovery_case = create_case()
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(create_payment()),
        query_result(None),
        query_result(0),
    ]
    patch_audit(monkeypatch)
    create_approval = AsyncMock()
    monkeypatch.setattr(
        recovery_plan_service,
        "create_recovery_approval_request",
        create_approval,
    )

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
        planner_result=planner_result(confidence=0.45),
    )

    assert result.actions[0].status == RecoveryActionStatus.ALLOWED.value
    assert recovery_case.status == RecoveryCaseStatus.READY.value
    assert result.approvals == ()
    create_approval.assert_not_awaited()


@pytest.mark.asyncio
async def test_persists_deterministic_fallback_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(create_case()),
        query_result(create_payment()),
        query_result(None),
        query_result(0),
    ]
    append_audit = patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(),
        alternate_payment_methods=(),
        planned_at=NOW,
        planner_result=planner_result(source=RecoveryPlannerSource.DETERMINISTIC),
    )

    assert result.agent_run.planner_provider == "deterministic"
    assert result.agent_run.evidence["planner"]["fallback_reason"] == "provider_error"
    audit_data = append_audit.await_args.kwargs["request"].event_data
    assert audit_data["fallback_used"] is True
    assert audit_data["fallback_reason"] == "provider_error"


@pytest.mark.asyncio
async def test_fresh_policy_stops_stale_gemini_recovery_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    recovery_case = create_case()
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(create_payment(state="authorized")),
        query_result(None),
        query_result(0),
    ]
    patch_audit(monkeypatch)

    result = await plan_and_persist_recovery_case(
        session,
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
        planner_result=planner_result(),
    )

    assert result.plan.decision is RecoveryPlanDecision.RECOVER
    assert result.actions[0].status == RecoveryActionStatus.STOPPED.value
    assert result.actions[0].policy_outcome == "stop"
    assert "payment_already_completed" in result.actions[0].policy_guardrails
    assert recovery_case.status == RecoveryCaseStatus.CANCELLED.value
    assert recovery_case.closed_at == NOW


@pytest.mark.asyncio
async def test_rejects_planner_result_from_another_planning_attempt() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(create_case()),
        query_result(create_payment()),
        query_result(None),
    ]

    with pytest.raises(RecoveryPlannerResultMismatchError, match="timestamp"):
        await plan_and_persist_recovery_case(
            session,
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=NOW,
            planner_result=planner_result(generated_at=NOW - timedelta(seconds=1)),
        )

    session.add.assert_not_called()
