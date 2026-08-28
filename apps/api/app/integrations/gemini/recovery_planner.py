import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self

from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings
from app.domain.recovery import (
    CUSTOMER_CONTACT_ACTIONS,
    DEFAULT_RECOVERY_PLANNER_POLICY,
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryChannel,
    RecoveryPlan,
    RecoveryPlanDecision,
    RecoveryPlanningContext,
    build_deterministic_recovery_plan,
    build_recovery_evidence_codes,
)

GEMINI_RECOVERY_PROMPT_VERSION = "gemini-structured-v2"

GEMINI_RECOVERY_SYSTEM_INSTRUCTION = """You are ReclaimRail's bounded payment-recovery planner.
You only propose actions; you never execute actions or contact customers.
Use only the supplied evidence. Never invent customer, payment, consent, or incident data.
Never change the original payment amount or currency.
Return at most three actions from the response schema.
Use stop_recovery when payment-completion evidence exists.
Use wait during a high or critical payment incident.
Use escalate_human when automation limits are reached.
Treat the supplied policy_contract as a hard decision envelope.
When required_decision is recover and create_payment_link is a baseline action,
propose create_payment_link for the exact original amount and currency.
Missing customer-contact consent forbids contact actions, but it does not forbid
creating an unshared Payment Link for an authorised merchant reviewer.
Do not escalate an otherwise eligible recovery merely because no contact channel
is approved.
Deterministic server-side policy will independently approve or reject every proposal.
Keep the reasoning summary concise and operational."""


GEMINI_RECOVERY_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "analysis": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "root_cause_category": {"type": "string"},
                "recoverability_assessment": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "allowed_action_recommendation": {"type": "string"},
                "evidence_references": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {"type": "string"},
                },
                "operator_explanation": {"type": "string"},
            },
            "required": [
                "root_cause_category",
                "recoverability_assessment",
                "confidence",
                "allowed_action_recommendation",
                "evidence_references",
                "operator_explanation",
            ],
        },
        "decision": {
            "type": "string",
            "enum": ["recover", "wait", "escalate", "stop"],
        },
        "reasoning_summary": {
            "type": "string",
        },
        "proposals": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": [
                            "create_payment_link",
                            "send_recovery_message",
                            "offer_alternate_method",
                            "wait",
                            "escalate_human",
                            "stop_recovery",
                        ],
                    },
                    "reason": {
                        "type": "string",
                    },
                    "amount_minor": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1},
                            {"type": "null"},
                        ],
                    },
                    "currency": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "null"},
                        ],
                    },
                    "channel": {
                        "anyOf": [
                            {
                                "type": "string",
                                "enum": ["email", "sms", "whatsapp"],
                            },
                            {"type": "null"},
                        ],
                    },
                    "target_payment_method": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "null"},
                        ],
                    },
                    "execute_after": {
                        "anyOf": [
                            {
                                "type": "string",
                                "format": "date-time",
                            },
                            {"type": "null"},
                        ],
                    },
                },
                "required": [
                    "action_type",
                    "reason",
                ],
            },
        },
    },
    "required": [
        "analysis",
        "decision",
        "reasoning_summary",
        "proposals",
    ],
}


class GeminiPlannerFallbackReason(StrEnum):
    NOT_CONFIGURED = "not_configured"
    PROVIDER_ERROR = "provider_error"
    INVALID_RESPONSE = "invalid_response"
    POLICY_CONFLICT = "policy_conflict"


class RecoveryPlannerSource(StrEnum):
    DETERMINISTIC = "deterministic"
    GEMINI = "gemini"


class GeminiPlannerProviderError(RuntimeError):
    pass


class GeminiRecoveryActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: RecoveryActionType
    reason: str = Field(min_length=1, max_length=500)
    amount_minor: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    channel: RecoveryChannel | None = None
    target_payment_method: str | None = Field(default=None, min_length=1, max_length=64)
    execute_after: datetime | None = None

    @model_validator(mode="after")
    def validate_action_shape(self) -> Self:
        if self.action_type is RecoveryActionType.CREATE_PAYMENT_LINK and (
            self.amount_minor is None or self.currency is None
        ):
            raise ValueError("Payment-link action requires amount and currency")

        if (
            self.action_type
            in {
                RecoveryActionType.SEND_RECOVERY_MESSAGE,
                RecoveryActionType.OFFER_ALTERNATE_METHOD,
            }
            and self.channel is None
        ):
            raise ValueError("Customer-contact action requires a channel")

        if self.action_type is RecoveryActionType.WAIT and self.execute_after is None:
            raise ValueError("Wait action requires execute_after")

        return self


class GeminiRecoveryAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause_category: str = Field(min_length=1, max_length=80)
    recoverability_assessment: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0, le=1)
    allowed_action_recommendation: str = Field(min_length=1, max_length=80)
    evidence_references: tuple[str, ...] = Field(min_length=1, max_length=4)
    operator_explanation: str = Field(min_length=1, max_length=400)


class GeminiRecoveryPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: RecoveryPlanDecision
    analysis: GeminiRecoveryAnalysisPayload
    reasoning_summary: str = Field(min_length=1, max_length=800)
    proposals: tuple[GeminiRecoveryActionPayload, ...] = Field(
        min_length=1,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_decision_alignment(self) -> Self:
        action_types = tuple(proposal.action_type for proposal in self.proposals)

        if len(set(action_types)) != len(action_types):
            raise ValueError("Recovery plan cannot repeat an action type")

        expected_control_action = {
            RecoveryPlanDecision.WAIT: RecoveryActionType.WAIT,
            RecoveryPlanDecision.ESCALATE: RecoveryActionType.ESCALATE_HUMAN,
            RecoveryPlanDecision.STOP: RecoveryActionType.STOP_RECOVERY,
        }.get(self.decision)

        if expected_control_action is not None and action_types != (expected_control_action,):
            raise ValueError("Control decision must contain exactly its control action")

        if self.decision is RecoveryPlanDecision.RECOVER and any(
            action_type
            in {
                RecoveryActionType.WAIT,
                RecoveryActionType.ESCALATE_HUMAN,
                RecoveryActionType.STOP_RECOVERY,
            }
            for action_type in action_types
        ):
            raise ValueError("Recover decision cannot contain control actions")

        return self


@dataclass(frozen=True, slots=True)
class GeminiProviderResponse:
    structured_plan: object
    model_name: str
    input_token_count: int | None = None
    output_token_count: int | None = None


class GeminiRecoveryPlanProvider(Protocol):
    model_name: str

    async def generate_plan(
        self,
        context: RecoveryPlanningContext,
    ) -> GeminiProviderResponse: ...


@dataclass(frozen=True, slots=True)
class BoundedRecoveryPlannerResult:
    plan: RecoveryPlan
    source: RecoveryPlannerSource
    model_name: str | None
    fallback_used: bool
    fallback_reason: GeminiPlannerFallbackReason | None
    input_token_count: int | None = None
    output_token_count: int | None = None
    analysis: GeminiRecoveryAnalysisPayload | None = None

    def __post_init__(self) -> None:
        if self.source is RecoveryPlannerSource.GEMINI:
            if self.fallback_used or self.fallback_reason is not None or self.model_name is None:
                raise ValueError("Gemini result cannot contain deterministic fallback metadata")
        elif not self.fallback_used or self.fallback_reason is None:
            raise ValueError("Deterministic fallback result requires a fallback reason")


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def build_recovery_evidence_tools(context: RecoveryPlanningContext) -> dict[str, object]:
    """The four fixed, read-only evidence surfaces available to Gemini."""
    case = context.case
    failure = context.failure
    return {
        "payment_state_snapshot": {
            "ref": "payment_state_snapshot",
            "state": case.payment_state.value,
            "amount_minor": case.amount_minor,
            "currency": case.currency,
            "payment_method": case.payment_method,
            "late_authorization_detected": case.late_authorization_detected_at is not None,
        },
        "attempt_and_recovery_history": {
            "ref": "attempt_and_recovery_history",
            "recovery_attempt_count": case.recovery_attempt_count,
            "failure_count": failure.failure_count,
            "active_payment_link": case.active_payment_link_id is not None,
        },
        "payment_rail_incident_context": {
            "ref": "payment_rail_incident_context",
            "active_incident_severity": case.active_incident_severity.value
            if case.active_incident_severity
            else None,
        },
        "merchant_recovery_policy": {
            "ref": "merchant_recovery_policy",
            "customer_contact_allowed": case.customer_contact_allowed,
            "approved_channels": [channel.value for channel in context.available_channels],
            "maximum_recovery_attempts": DEFAULT_RECOVERY_PLANNER_POLICY.maximum_recovery_attempts,
            "automatic_amount_limit_minor": (
                DEFAULT_RECOVERY_PLANNER_POLICY.automatic_amount_limit_minor
            ),
        },
    }


def build_recovery_planning_prompt(
    context: RecoveryPlanningContext,
) -> str:
    case = context.case
    failure = context.failure
    deterministic_baseline = build_deterministic_recovery_plan(context)
    evidence = {
        "case": {
            "case_id": str(case.case_id),
            "provider_payment_id": case.provider_payment_id,
            "payment_state": case.payment_state.value,
            "amount_minor": case.amount_minor,
            "currency": case.currency,
            "payment_method": case.payment_method,
            "status": case.status.value,
            "recovery_attempt_count": case.recovery_attempt_count,
            "customer_contact_allowed": case.customer_contact_allowed,
            "last_customer_contact_at": _timestamp(case.last_customer_contact_at),
            "active_payment_link": case.active_payment_link_id is not None,
            "active_incident_severity": (
                case.active_incident_severity.value
                if case.active_incident_severity is not None
                else None
            ),
            "late_authorization_detected_at": _timestamp(
                case.late_authorization_detected_at,
            ),
        },
        "failure": {
            "error_code": failure.error_code,
            "error_source": failure.error_source,
            "error_step": failure.error_step,
            "error_reason": failure.error_reason,
            "failure_count": failure.failure_count,
            "first_failed_at": failure.first_failed_at.isoformat(),
            "last_failed_at": failure.last_failed_at.isoformat(),
        },
        "approved_channels": [channel.value for channel in context.available_channels],
        "alternate_payment_methods": list(context.alternate_payment_methods),
        "policy_contract": {
            "automatic_amount_limit_minor": (
                DEFAULT_RECOVERY_PLANNER_POLICY.automatic_amount_limit_minor
            ),
            "maximum_recovery_attempts": (
                DEFAULT_RECOVERY_PLANNER_POLICY.maximum_recovery_attempts
            ),
            "required_decision": deterministic_baseline.decision.value,
            "baseline_action_types": [
                proposal.action_type.value for proposal in deterministic_baseline.proposals
            ],
            "customer_contact_actions_allowed": bool(
                case.customer_contact_allowed and context.available_channels,
            ),
        },
        "planned_at": context.planned_at.isoformat(),
        "read_only_evidence_tools": build_recovery_evidence_tools(context),
    }
    return "Plan the next bounded recovery step from this evidence:\n" + json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
    )


class GoogleGenAIRecoveryPlanProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        temperature: float = 0.1,
        max_output_tokens: int = 1024,
        request_timeout_seconds: float = 8.0,
    ) -> None:
        normalized_api_key = api_key.strip()
        normalized_model_name = model_name.strip()

        if not normalized_api_key:
            raise ValueError("Gemini API key cannot be empty")
        if not normalized_model_name:
            raise ValueError("Gemini model name cannot be empty")
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("Gemini temperature must be between zero and one")
        if not 256 <= max_output_tokens <= 4096:
            raise ValueError("Gemini output-token limit must be between 256 and 4096")
        if not 1.0 <= request_timeout_seconds <= 60.0:
            raise ValueError("Gemini request timeout must be between 1 and 60 seconds")

        self._api_key = normalized_api_key
        self.model_name = normalized_model_name
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._request_timeout_seconds = request_timeout_seconds

    async def generate_plan(
        self,
        context: RecoveryPlanningContext,
    ) -> GeminiProviderResponse:
        client = genai.Client(api_key=self._api_key)
        async_client = client.aio

        try:
            async with asyncio.timeout(self._request_timeout_seconds):
                response = await async_client.models.generate_content(
                    model=self.model_name,
                    contents=build_recovery_planning_prompt(context),
                    config=types.GenerateContentConfig(
                        system_instruction=GEMINI_RECOVERY_SYSTEM_INSTRUCTION,
                        temperature=self._temperature,
                        candidate_count=1,
                        max_output_tokens=self._max_output_tokens,
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.MINIMAL,
                        ),
                        response_mime_type="application/json",
                        response_json_schema=GEMINI_RECOVERY_RESPONSE_JSON_SCHEMA,
                    ),
                )

            if not response.text:
                raise GeminiPlannerProviderError(
                    "Gemini response did not contain a structured recovery plan",
                )

            usage = response.usage_metadata
            return GeminiProviderResponse(
                structured_plan=response.text,
                model_name=self.model_name,
                input_token_count=(usage.prompt_token_count if usage is not None else None),
                output_token_count=(usage.candidates_token_count if usage is not None else None),
            )
        except GeminiPlannerProviderError:
            raise
        except Exception as error:
            raise GeminiPlannerProviderError(
                f"Gemini recovery planning failed: {type(error).__name__}",
            ) from error
        finally:
            await async_client.aclose()
            client.close()


def create_gemini_recovery_plan_provider(
    settings: Settings,
) -> GoogleGenAIRecoveryPlanProvider | None:
    if settings.gemini_api_key is None:
        return None

    api_key = settings.gemini_api_key.get_secret_value().strip()
    if not api_key:
        return None

    return GoogleGenAIRecoveryPlanProvider(
        api_key=api_key,
        model_name=settings.gemini_model_name,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
        request_timeout_seconds=settings.gemini_request_timeout_seconds,
    )


def _convert_gemini_plan(
    payload: GeminiRecoveryPlanPayload,
    *,
    context: RecoveryPlanningContext,
) -> RecoveryPlan:
    proposals = tuple(
        RecoveryActionProposal(
            action_type=proposal.action_type,
            reason=proposal.reason,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            channel=proposal.channel,
            target_payment_method=proposal.target_payment_method,
            execute_after=proposal.execute_after,
        )
        for proposal in payload.proposals
    )
    return RecoveryPlan(
        decision=payload.decision,
        reasoning_summary=payload.reasoning_summary,
        proposals=proposals,
        evidence_codes=build_recovery_evidence_codes(context),
        generated_at=context.planned_at,
        planner_version=GEMINI_RECOVERY_PROMPT_VERSION,
    )


def _deterministic_fallback(
    context: RecoveryPlanningContext,
    *,
    reason: GeminiPlannerFallbackReason,
) -> BoundedRecoveryPlannerResult:
    return BoundedRecoveryPlannerResult(
        plan=build_deterministic_recovery_plan(context),
        source=RecoveryPlannerSource.DETERMINISTIC,
        model_name=None,
        fallback_used=True,
        fallback_reason=reason,
    )


def _violates_policy_contract(
    plan: RecoveryPlan,
    *,
    context: RecoveryPlanningContext,
) -> bool:
    baseline = build_deterministic_recovery_plan(context)

    if plan.decision is not baseline.decision:
        return True

    if (not context.case.customer_contact_allowed or not context.available_channels) and any(
        proposal.action_type in CUSTOMER_CONTACT_ACTIONS for proposal in plan.proposals
    ):
        return True

    baseline_requires_link = any(
        proposal.action_type is RecoveryActionType.CREATE_PAYMENT_LINK
        for proposal in baseline.proposals
    )
    if not baseline_requires_link:
        return False

    payment_link_proposal = next(
        (
            proposal
            for proposal in plan.proposals
            if proposal.action_type is RecoveryActionType.CREATE_PAYMENT_LINK
        ),
        None,
    )
    return payment_link_proposal is None or (
        payment_link_proposal.amount_minor != context.case.amount_minor
        or payment_link_proposal.currency != context.case.currency
    )


async def plan_with_gemini_fallback(
    context: RecoveryPlanningContext,
    *,
    provider: GeminiRecoveryPlanProvider | None,
) -> BoundedRecoveryPlannerResult:
    if provider is None:
        return _deterministic_fallback(
            context,
            reason=GeminiPlannerFallbackReason.NOT_CONFIGURED,
        )

    try:
        response = await provider.generate_plan(context)
    except GeminiPlannerProviderError:
        return _deterministic_fallback(
            context,
            reason=GeminiPlannerFallbackReason.PROVIDER_ERROR,
        )

    try:
        if isinstance(response.structured_plan, str):
            payload = GeminiRecoveryPlanPayload.model_validate_json(
                response.structured_plan,
            )
        else:
            payload = GeminiRecoveryPlanPayload.model_validate(
                response.structured_plan,
            )
        plan = _convert_gemini_plan(payload, context=context)
    except (TypeError, ValueError, ValidationError):
        return _deterministic_fallback(
            context,
            reason=GeminiPlannerFallbackReason.INVALID_RESPONSE,
        )

    if _violates_policy_contract(plan, context=context):
        return _deterministic_fallback(
            context,
            reason=GeminiPlannerFallbackReason.POLICY_CONFLICT,
        )

    valid_evidence_references = set(build_recovery_evidence_tools(context))
    if not set(payload.analysis.evidence_references).issubset(valid_evidence_references):
        return _deterministic_fallback(
            context,
            reason=GeminiPlannerFallbackReason.INVALID_RESPONSE,
        )

    return BoundedRecoveryPlannerResult(
        plan=plan,
        source=RecoveryPlannerSource.GEMINI,
        model_name=response.model_name,
        fallback_used=False,
        fallback_reason=None,
        input_token_count=response.input_token_count,
        output_token_count=response.output_token_count,
        analysis=payload.analysis,
    )
