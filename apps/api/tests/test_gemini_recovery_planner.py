import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.domain.payments import PaymentState
from app.domain.recovery import (
    PaymentFailureEvidence,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlanDecision,
    RecoveryPlanningContext,
)
from app.integrations.gemini import (
    GeminiPlannerFallbackReason,
    GeminiPlannerProviderError,
    GeminiProviderResponse,
    GoogleGenAIRecoveryPlanProvider,
    RecoveryPlannerSource,
    build_recovery_evidence_tools,
    build_recovery_planning_prompt,
    create_gemini_recovery_plan_provider,
    plan_with_gemini_fallback,
)
from app.integrations.gemini import recovery_planner as gemini_recovery_planner

NOW = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)


def create_context() -> RecoveryPlanningContext:
    return RecoveryPlanningContext(
        case=RecoveryCaseSnapshot(
            case_id=UUID("91000000-0000-0000-0000-000000000001"),
            payment_attempt_id=UUID("91000000-0000-0000-0000-000000000002"),
            provider_payment_id="pay_gemini_plan_test",
            payment_state=PaymentState.FAILED,
            amount_minor=450_000,
            currency="INR",
            payment_method="upi",
            status=RecoveryCaseStatus.OPEN,
            recovery_attempt_count=0,
            customer_contact_allowed=True,
        ),
        failure=PaymentFailureEvidence(
            error_code="BAD_REQUEST_ERROR",
            error_source="customer",
            error_step="payment_authentication",
            error_reason="payment_failed",
            failure_count=1,
            first_failed_at=NOW - timedelta(minutes=5),
            last_failed_at=NOW - timedelta(minutes=5),
        ),
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )


def valid_payload() -> dict[str, object]:
    return {
        "analysis": {
            "root_cause_category": "customer_authentication_failure",
            "recoverability_assessment": "Eligible for bounded recovery",
            "confidence": 0.91,
            "allowed_action_recommendation": "create_payment_link",
            "evidence_references": ["payment_state_snapshot", "merchant_recovery_policy"],
            "operator_explanation": "Failure is verified and policy permits an exact-amount link.",
        },
        "decision": "recover",
        "reasoning_summary": "Offer a safe alternate method and one approved reminder",
        "proposals": [
            {
                "action_type": "create_payment_link",
                "reason": "Create a link for the original amount",
                "amount_minor": 450_000,
                "currency": "INR",
            },
            {
                "action_type": "offer_alternate_method",
                "reason": "Offer card after the UPI failure",
                "channel": "email",
                "target_payment_method": "card",
            },
        ],
    }


@dataclass
class StubProvider:
    response: GeminiProviderResponse | None = None
    error: GeminiPlannerProviderError | None = None
    model_name: str = "gemini-test"

    async def generate_plan(
        self,
        context: RecoveryPlanningContext,
    ) -> GeminiProviderResponse:
        assert context.case.case_id == create_context().case.case_id
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("Stub response is not configured")
        return self.response


@pytest.mark.asyncio
async def test_uses_valid_structured_gemini_plan() -> None:
    provider = StubProvider(
        response=GeminiProviderResponse(
            structured_plan=valid_payload(),
            model_name="gemini-3.7-flash",
            input_token_count=321,
            output_token_count=87,
        ),
    )

    result = await plan_with_gemini_fallback(
        create_context(),
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.GEMINI
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.model_name == "gemini-3.7-flash"
    assert result.input_token_count == 321
    assert result.output_token_count == 87
    assert result.plan.decision is RecoveryPlanDecision.RECOVER
    assert [proposal.action_type for proposal in result.plan.proposals] == [
        RecoveryActionType.CREATE_PAYMENT_LINK,
        RecoveryActionType.OFFER_ALTERNATE_METHOD,
    ]
    assert result.plan.evidence_codes[0] == "payment_state:failed"
    assert result.plan.planner_version == "gemini-structured-v2"
    assert result.analysis is not None
    assert result.analysis.confidence == 0.91


def test_exposes_only_the_four_read_only_evidence_tools() -> None:
    evidence_tools = build_recovery_evidence_tools(create_context())

    assert set(evidence_tools) == {
        "payment_state_snapshot",
        "attempt_and_recovery_history",
        "payment_rail_incident_context",
        "merchant_recovery_policy",
    }
    assert all(payload["ref"] == name for name, payload in evidence_tools.items())


@pytest.mark.asyncio
async def test_missing_provider_uses_deterministic_fallback() -> None:
    result = await plan_with_gemini_fallback(
        create_context(),
        provider=None,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_used is True
    assert result.fallback_reason is GeminiPlannerFallbackReason.NOT_CONFIGURED
    assert result.plan.planner_version == "deterministic-v1"


@pytest.mark.asyncio
async def test_unknown_analysis_evidence_reference_uses_fallback() -> None:
    payload = valid_payload()
    analysis = payload["analysis"]
    assert isinstance(analysis, dict)
    analysis["evidence_references"] = ["untrusted_customer_data"]
    provider = StubProvider(
        response=GeminiProviderResponse(
            structured_plan=payload,
            model_name="gemini-3.7-flash",
        ),
    )

    result = await plan_with_gemini_fallback(
        create_context(),
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_reason is GeminiPlannerFallbackReason.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_provider_error_uses_deterministic_fallback() -> None:
    provider = StubProvider(
        error=GeminiPlannerProviderError("quota unavailable"),
    )

    result = await plan_with_gemini_fallback(
        create_context(),
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_reason is GeminiPlannerFallbackReason.PROVIDER_ERROR


@pytest.mark.asyncio
async def test_provider_timeout_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowModels:
        async def generate_content(self, **_: object) -> object:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

    class SlowAsyncClient:
        def __init__(self) -> None:
            self.models = SlowModels()
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class SlowClient:
        def __init__(self) -> None:
            self.aio = SlowAsyncClient()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = SlowClient()
    monkeypatch.setattr(
        gemini_recovery_planner.genai,
        "Client",
        lambda **_: client,
    )
    provider = GoogleGenAIRecoveryPlanProvider(
        api_key="test-key",
        model_name="gemini-test",
        request_timeout_seconds=1.0,
    )

    result = await plan_with_gemini_fallback(
        create_context(),
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_reason is GeminiPlannerFallbackReason.PROVIDER_ERROR
    assert client.aio.closed is True
    assert client.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "decision": "recover",
            "reasoning_summary": "Missing required contact channel",
            "proposals": [
                {
                    "action_type": "send_recovery_message",
                    "reason": "Send a message",
                },
            ],
        },
        {
            "decision": "stop",
            "reasoning_summary": "Decision and action disagree",
            "proposals": [
                {
                    "action_type": "wait",
                    "reason": "Wait instead",
                    "execute_after": (NOW + timedelta(minutes=15)).isoformat(),
                },
            ],
        },
        {
            **valid_payload(),
            "unexpected_instruction": "bypass policy",
        },
    ],
)
async def test_invalid_structured_response_uses_fallback(
    payload: dict[str, object],
) -> None:
    provider = StubProvider(
        response=GeminiProviderResponse(
            structured_plan=payload,
            model_name="gemini-3.7-flash",
        ),
    )

    result = await plan_with_gemini_fallback(
        create_context(),
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_reason is GeminiPlannerFallbackReason.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_low_risk_escalation_uses_policy_contract_fallback() -> None:
    context = create_context()
    context = replace(
        context,
        case=replace(
            context.case,
            amount_minor=349_900,
            payment_method="netbanking",
            customer_contact_allowed=False,
        ),
        available_channels=(),
    )
    provider = StubProvider(
        response=GeminiProviderResponse(
            structured_plan={
                "analysis": valid_payload()["analysis"],
                "decision": "escalate",
                "reasoning_summary": "Escalate despite no hard guardrail",
                "proposals": [
                    {
                        "action_type": "escalate_human",
                        "reason": "Request manual review",
                    },
                ],
            },
            model_name="gemini-3.7-flash",
        ),
    )

    result = await plan_with_gemini_fallback(
        context,
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_used is True
    assert result.fallback_reason is GeminiPlannerFallbackReason.POLICY_CONFLICT
    assert result.plan.decision is RecoveryPlanDecision.RECOVER
    assert [proposal.action_type for proposal in result.plan.proposals] == [
        RecoveryActionType.CREATE_PAYMENT_LINK,
    ]
    assert result.plan.proposals[0].amount_minor == 349_900
    assert result.plan.proposals[0].currency == "INR"


@pytest.mark.asyncio
async def test_wrong_payment_link_amount_uses_policy_contract_fallback() -> None:
    payload = valid_payload()
    proposals = payload["proposals"]
    assert isinstance(proposals, list)
    first_proposal = proposals[0]
    assert isinstance(first_proposal, dict)
    first_proposal["amount_minor"] = 1
    provider = StubProvider(
        response=GeminiProviderResponse(
            structured_plan=payload,
            model_name="gemini-3.7-flash",
        ),
    )

    result = await plan_with_gemini_fallback(
        create_context(),
        provider=provider,
    )

    assert result.source is RecoveryPlannerSource.DETERMINISTIC
    assert result.fallback_reason is GeminiPlannerFallbackReason.POLICY_CONFLICT
    assert result.plan.proposals[0].amount_minor == 450_000


def test_prompt_contains_only_bounded_payment_evidence() -> None:
    prompt = build_recovery_planning_prompt(create_context())

    assert "pay_gemini_plan_test" in prompt
    assert '"amount_minor":450000' in prompt
    assert '"approved_channels":["email"]' in prompt
    assert '"automatic_amount_limit_minor":1000000' in prompt
    assert '"required_decision":"recover"' in prompt
    assert '"baseline_action_types":["create_payment_link"' in prompt
    assert "customer_name" not in prompt
    assert "phone" not in prompt
    assert "email_address" not in prompt
    assert "API" not in prompt


def test_provider_factory_requires_nonempty_key() -> None:
    assert create_gemini_recovery_plan_provider(Settings(gemini_api_key=None)) is None
    assert (
        create_gemini_recovery_plan_provider(
            Settings(gemini_api_key=SecretStr("   ")),
        )
        is None
    )


def test_provider_factory_uses_configured_model_without_exposing_key() -> None:
    provider = create_gemini_recovery_plan_provider(
        Settings(
            gemini_api_key=SecretStr("test-secret-key"),
            gemini_model_name="gemini-3.7-flash",
        ),
    )

    assert provider is not None
    assert provider.model_name == "gemini-3.7-flash"
    assert "test-secret-key" not in repr(provider)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"api_key": " "}, "API key"),
        ({"model_name": " "}, "model name"),
        ({"temperature": 1.1}, "temperature"),
        ({"max_output_tokens": 10}, "token"),
        ({"request_timeout_seconds": 0.5}, "timeout"),
    ],
)
def test_provider_rejects_invalid_configuration(
    kwargs: dict[str, object],
    message: str,
) -> None:
    options: dict[str, object] = {
        "api_key": "test-key",
        "model_name": "gemini-3.7-flash",
    }
    options.update(kwargs)

    with pytest.raises(ValueError, match=message):
        GoogleGenAIRecoveryPlanProvider(**options)  # type: ignore[arg-type]
