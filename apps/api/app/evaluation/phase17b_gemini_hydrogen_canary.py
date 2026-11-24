"""Controlled multi-turn Hydrogen canary with frozen observations and no tool execution."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol

from google import genai
from google.genai import types as genai_types
from pydantic import ValidationError

from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.evaluation.phase17b_benchmark import (
    BenchmarkScenarioResult,
    FrozenInvestigationScenario,
    FrozenToolObservation,
    run_frozen_scenario,
)
from app.evaluation.phase17b_gemini38_smoke import gemini_tool_declarations
from app.integrations.gemini.evidence_investigator import (
    INVESTIGATOR_SYSTEM_INSTRUCTION,
    _classify_provider_error,
    build_gemini_generate_content_config,
    build_investigator_prompt,
)
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)
from app.services.recovery_investigation_tools import CaseToolArguments

HYDROGEN_MODEL: Final = "gemini-4-hydrogen"
GEMINI_35_FLASH_MODEL: Final = "gemini-3.5-flash"
CANARY_MODELS: Final = frozenset({GEMINI_35_FLASH_MODEL, HYDROGEN_MODEL})
CANARY_CASE_ID: Final = "00000000-0000-4000-8000-000000000018"
SOURCE_RECEIPT_SHA256: Final = "9ecc2c33888baeecb147d95cb610cfa9f62aa28e6f7e6699a244aa4d86126214"
MAX_REQUEST_STARTS: Final = 3
REQUEST_TIMEOUT_SECONDS: Final = 120.0
MAX_OUTPUT_TOKENS: Final = 512
THINKING_LEVEL: Final = "low"
_MODEL_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FROZEN_TOOL_NAMES: Final = frozenset({"get_truth_snapshot", "get_verified_webhooks"})
_TERMINAL_NAMES: Final = frozenset({"complete_investigation", "abstain_investigation"})
_SAFE_RATE_HEADERS: Final = {
    "retry-after": "retry_after_seconds",
    "x-ratelimit-limit-requests": "request_limit",
    "x-ratelimit-remaining-requests": "request_remaining",
    "x-ratelimit-limit-tokens": "token_limit",
    "x-ratelimit-remaining-tokens": "token_remaining",
}


class _Interactions(Protocol):
    async def create(self, **kwargs: object) -> object: ...


class _AsyncClient(Protocol):
    interactions: _Interactions

    async def aclose(self) -> None: ...


class _Client(Protocol):
    aio: _AsyncClient

    def close(self) -> None: ...


ClientFactory = Callable[[str, float], _Client]


class ValidationFailureReason(StrEnum):
    FUNCTION_CALL_COUNT = "function_call_count"
    INVALID_FUNCTION_NAME = "invalid_function_name"
    TERMINAL_ARGUMENTS_NOT_OBJECT = "terminal_arguments_not_object"
    TERMINAL_SCHEMA_INVALID = "terminal_schema_invalid"
    UNSUPPORTED_FUNCTION = "unsupported_function"
    TOOL_ARGUMENTS_SCHEMA_INVALID = "tool_arguments_schema_invalid"
    CASE_ID_MISMATCH = "case_id_mismatch"
    MISSING_INTERACTION_ID = "missing_interaction_id"
    MISSING_CALL_ID = "missing_call_id"


class _CanaryValidationError(ValueError):
    def __init__(self, reason: ValidationFailureReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class HydrogenTurnReceipt:
    number: int
    classification: Literal["tool", "terminal_complete", "terminal_abstain", "failed_safe"]
    public_name: str | None
    http_status: int | None
    http_category: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    arguments_valid: bool | None
    function_result_linked: bool | None
    validation_failure_reason: ValidationFailureReason | None
    quota_metadata: dict[str, int] | None


@dataclass(frozen=True, slots=True)
class HydrogenCanaryReport:
    schema_version: Literal["phase17b-gemini-hydrogen-canary-v1"]
    source_receipt_sha256: str
    provider: Literal["gemini"]
    model: str
    thinking_level: Literal["low"]
    max_output_tokens: int
    timeout_seconds: int
    max_request_starts: int
    requests_started: int
    responses_received: int
    retries: int
    failover: int
    automatic_continuation_disabled: bool
    tool_execution_count: int
    turns: tuple[HydrogenTurnReceipt, ...]
    function_linkage_passed: bool
    terminal_action: str | None
    citations_valid: bool
    truth_compatible: bool
    failed_safe: bool
    final_status: str


@dataclass(frozen=True, slots=True)
class _PendingFunction:
    interaction_id: str
    call_id: str
    name: str


def controlled_canary_scenario() -> FrozenInvestigationScenario:
    """Return the legacy controlled canary as one isolated frozen engine scenario."""

    return FrozenInvestigationScenario(
        scenario_id="p17b-18",
        objective="Inspect only supplied synthetic evidence and take no action.",
        case_payload={"case_id": CANARY_CASE_ID, "version": 0},
        required_tools=("get_truth_snapshot", "get_verified_webhooks"),
        expected_terminal="abstain",
        expected_evidence_ids=("canary-evidence-1", "canary-evidence-2"),
        tool_observations={
            "get_truth_snapshot": FrozenToolObservation(
                outcome="succeeded",
                evidence_ids=("canary-evidence-1",),
                payload={"mode": "controlled_synthetic", "sequence": 1},
            ),
            "get_verified_webhooks": FrozenToolObservation(
                outcome="succeeded",
                evidence_ids=("canary-evidence-2",),
                payload={"mode": "controlled_synthetic", "sequence": 2},
            ),
        },
    )


def interaction_tool_declarations(request: dict[str, object]) -> list[dict[str, object]]:
    """Reuse the validated declarations while emitting the Interactions wire shape."""

    config = build_gemini_generate_content_config(
        request,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_level=THINKING_LEVEL,
    )
    tools = config.tools or []
    if len(tools) != 1 or not isinstance(tools[0], genai_types.Tool):
        raise ValueError("Hydrogen canary declarations are malformed")
    declarations: list[dict[str, object]] = []
    for function in tools[0].function_declarations or []:
        if not function.name or not function.description or not function.parameters_json_schema:
            raise ValueError("Hydrogen canary function declaration is incomplete")
        declarations.append(
            {
                "type": "function",
                "name": function.name,
                "description": function.description,
                "parameters": function.parameters_json_schema,
            }
        )
    expected_names = {item["name"] for item in gemini_tool_declarations()} | _TERMINAL_NAMES
    if {item["name"] for item in declarations} != expected_names:
        raise ValueError("Hydrogen canary declarations do not match the authoritative catalog")
    return declarations


def _default_client_factory(api_key: str, timeout_seconds: float) -> _Client:
    return genai.Client(  # type: ignore[return-value]
        api_key=api_key,
        http_options=genai_types.HttpOptions(
            api_version="v1beta",
            timeout=int(timeout_seconds * 1000),
            retry_options=genai_types.HttpRetryOptions(attempts=1),
        ),
    )


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _safe_quota(error: BaseException) -> dict[str, int] | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    normalized = {str(key).casefold(): value for key, value in headers.items()}
    safe: dict[str, int] = {}
    for header, field in _SAFE_RATE_HEADERS.items():
        value = _integer(normalized.get(header))
        if value is not None:
            safe[field] = value
    return safe or None


def _usage(response: object) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    return (
        _integer(getattr(usage, "total_input_tokens", None)),
        _integer(getattr(usage, "total_output_tokens", None)),
        _integer(getattr(usage, "total_thought_tokens", None)),
    )


def _error_category(error: EvidenceInvestigatorProviderError) -> str:
    return error.kind.value


def _terminal_turn(name: str, arguments: object) -> InvestigatorTurn:
    if not isinstance(arguments, dict):
        raise _CanaryValidationError(ValidationFailureReason.TERMINAL_ARGUMENTS_NOT_OBJECT)
    try:
        if name == "complete_investigation":
            return InvestigatorTurn.model_validate(
                {**arguments, "action": InvestigationTurnAction.COMPLETE}
            )
        return InvestigatorTurn.model_validate(
            {**arguments, "action": InvestigationTurnAction.ABSTAIN}
        )
    except ValidationError:
        raise _CanaryValidationError(ValidationFailureReason.TERMINAL_SCHEMA_INVALID) from None


class HydrogenCanaryProvider:
    """Stateful Interactions adapter used only by the controlled Hydrogen canary."""

    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = HYDROGEN_MODEL,
        client_factory: ClientFactory = _default_client_factory,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Hydrogen canary key cannot be empty")
        if model_name not in CANARY_MODELS:
            raise ValueError("Controlled canary model is not allowlisted")
        self.model_name = model_name
        self._client = client_factory(api_key.strip(), REQUEST_TIMEOUT_SECONDS)
        self._async_client = self._client.aio
        self._pending: _PendingFunction | None = None
        self._observation_count = 0
        self._tool_calls_returned = 0
        self._function_results_submitted = 0
        self._terminal_returned = False
        self.request_starts = 0
        self.responses_received = 0
        self.turn_receipts: list[HydrogenTurnReceipt] = []

    @property
    def function_linkage_passed(self) -> bool:
        return (
            self._terminal_returned
            and self._pending is None
            and self._tool_calls_returned > 0
            and self._function_results_submitted == self._tool_calls_returned
        )

    async def aclose(self) -> None:
        await self._async_client.aclose()
        self._client.close()

    def _continuation_input(
        self,
        request: dict[str, object],
    ) -> tuple[list[dict[str, object]], str, bool]:
        pending = self._pending
        if pending is None:
            raise ValueError("Hydrogen canary has no pending function result")
        observations = request.get("observations")
        if not isinstance(observations, list) or len(observations) != self._observation_count + 1:
            raise ValueError("Hydrogen canary observation linkage is missing or duplicated")
        observation = observations[-1]
        if not isinstance(observation, dict) or observation.get("tool") != pending.name:
            raise ValueError("Hydrogen canary observation does not match the pending function")
        return (
            [
                {
                    "type": "function_result",
                    "name": pending.name,
                    "call_id": pending.call_id,
                    "result": [
                        {
                            "type": "text",
                            "text": json.dumps(observation, sort_keys=True, separators=(",", ":")),
                        }
                    ],
                }
            ],
            pending.interaction_id,
            True,
        )

    def _request_body(self, request: dict[str, object]) -> tuple[dict[str, object], bool]:
        tools = interaction_tool_declarations(request)
        common: dict[str, object] = {
            "model": self.model_name,
            "tools": tools,
            "store": True,
            "generation_config": {
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "thinking_level": THINKING_LEVEL,
            },
            "timeout": REQUEST_TIMEOUT_SECONDS,
            "automatic_continuation": False,
        }
        if self._pending is None:
            observations = request.get("observations")
            if self.request_starts != 0 or observations not in ([], ()):
                raise ValueError("Hydrogen canary initial request state is invalid")
            return {
                **common,
                "input": build_investigator_prompt(request),
                "system_instruction": INVESTIGATOR_SYSTEM_INSTRUCTION,
            }, False
        interaction_input, previous_interaction_id, linked = self._continuation_input(request)
        return {
            **common,
            "input": interaction_input,
            "previous_interaction_id": previous_interaction_id,
        }, linked

    async def _provider_call(self, body: dict[str, object]) -> tuple[object, float]:
        started = time.monotonic_ns()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                response = await self._async_client.interactions.create(**body)
        except Exception as error:  # noqa: BLE001 - sanitized provider boundary
            latency = round((time.monotonic_ns() - started) / 1_000_000, 3)
            classified = _classify_provider_error(error)
            self.turn_receipts.append(
                HydrogenTurnReceipt(
                    number=self.request_starts,
                    classification="failed_safe",
                    public_name=None,
                    http_status=classified.status_code,
                    http_category=_error_category(classified),
                    latency_ms=latency,
                    input_tokens=None,
                    output_tokens=None,
                    thinking_tokens=None,
                    arguments_valid=None,
                    function_result_linked=None,
                    validation_failure_reason=None,
                    quota_metadata=_safe_quota(error),
                )
            )
            raise classified from None
        return response, round((time.monotonic_ns() - started) / 1_000_000, 3)

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        if self._terminal_returned:
            raise ValueError("Hydrogen canary cannot continue after a terminal response")
        if self.request_starts >= MAX_REQUEST_STARTS:
            raise EvidenceInvestigatorProviderError(
                "Hydrogen canary request-start ceiling reached",
                kind=EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE,
                retryable=False,
            )
        body, linked_prior = self._request_body(request)
        self.request_starts += 1
        if linked_prior:
            self._function_results_submitted += 1
            self._observation_count += 1
        response, latency = await self._provider_call(body)
        self.responses_received += 1
        input_tokens, output_tokens, thinking_tokens = _usage(response)
        try:
            steps = getattr(response, "steps", None)
            calls = [step for step in steps or [] if getattr(step, "type", None) == "function_call"]
            if len(calls) != 1:
                raise _CanaryValidationError(ValidationFailureReason.FUNCTION_CALL_COUNT)
            call = calls[0]
            name = getattr(call, "name", None)
            arguments = getattr(call, "arguments", None)
            if not isinstance(name, str) or not _MODEL_PATTERN.fullmatch(name):
                raise _CanaryValidationError(ValidationFailureReason.INVALID_FUNCTION_NAME)
            interaction_id = getattr(response, "id", None)
            call_id = getattr(call, "id", None)
            self._pending = None
            classification: Literal["tool", "terminal_complete", "terminal_abstain"]
            if name in _TERMINAL_NAMES:
                turn = _terminal_turn(name, arguments)
                self._terminal_returned = True
                classification = (
                    "terminal_complete"
                    if turn.action is InvestigationTurnAction.COMPLETE
                    else "terminal_abstain"
                )
                arguments_valid = True
            else:
                if name not in _FROZEN_TOOL_NAMES:
                    raise _CanaryValidationError(ValidationFailureReason.UNSUPPORTED_FUNCTION)
                try:
                    parsed = CaseToolArguments.model_validate(arguments)
                except ValidationError:
                    raise _CanaryValidationError(
                        ValidationFailureReason.TOOL_ARGUMENTS_SCHEMA_INVALID
                    ) from None
                case = request.get("case")
                if not isinstance(case, dict) or str(parsed.case_id) != case.get("case_id"):
                    raise _CanaryValidationError(ValidationFailureReason.CASE_ID_MISMATCH)
                if not isinstance(interaction_id, str) or not interaction_id:
                    raise _CanaryValidationError(ValidationFailureReason.MISSING_INTERACTION_ID)
                if not isinstance(call_id, str) or not call_id:
                    raise _CanaryValidationError(ValidationFailureReason.MISSING_CALL_ID)
                self._pending = _PendingFunction(interaction_id, call_id, name)
                self._tool_calls_returned += 1
                turn = InvestigatorTurn(
                    action=InvestigationTurnAction.CALL_TOOL,
                    tool_name=name,
                    tool_arguments=arguments,
                )
                classification = "tool"
                arguments_valid = True
        except _CanaryValidationError as error:
            self.turn_receipts.append(
                HydrogenTurnReceipt(
                    number=self.request_starts,
                    classification="failed_safe",
                    public_name=None,
                    http_status=200,
                    http_category="malformed_response",
                    latency_ms=latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    thinking_tokens=thinking_tokens,
                    arguments_valid=False,
                    function_result_linked=linked_prior or None,
                    validation_failure_reason=error.reason,
                    quota_metadata=None,
                )
            )
            raise EvidenceInvestigatorProviderError(
                "Hydrogen returned an invalid controlled-canary response",
                kind=EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE,
                retryable=False,
                status_code=200,
            ) from None
        self.turn_receipts.append(
            HydrogenTurnReceipt(
                number=self.request_starts,
                classification=classification,
                public_name=name,
                http_status=200,
                http_category="success",
                latency_ms=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking_tokens,
                arguments_valid=arguments_valid,
                function_result_linked=linked_prior or None,
                validation_failure_reason=None,
                quota_metadata=None,
            )
        )
        return InvestigatorProviderResponse(
            turn=turn,
            model_name=self.model_name,
            model_version=self.model_name,
            input_token_count=input_tokens,
            output_token_count=output_tokens,
            provider=self.provider_name,
        )


def _final_status(result: BenchmarkScenarioResult, linkage_passed: bool) -> str:
    if result.provider_failed:
        return result.terminal_reason
    if result.malformed_output:
        return result.terminal_reason
    if result.terminal_action not in {"complete", "abstain"}:
        return result.terminal_reason
    if not linkage_passed:
        return "function_linkage_failed"
    if not result.citations_valid:
        return "invalid_citations"
    if not result.failed_safe:
        return "unsafe_terminal_response"
    if not result.truth_compatible:
        return "truth_incompatible_terminal"
    return "passed"


def build_canary_report(
    provider: HydrogenCanaryProvider,
    result: BenchmarkScenarioResult,
) -> HydrogenCanaryReport:
    return HydrogenCanaryReport(
        schema_version="phase17b-gemini-hydrogen-canary-v1",
        source_receipt_sha256=SOURCE_RECEIPT_SHA256,
        provider="gemini",
        model=provider.model_name,
        thinking_level=THINKING_LEVEL,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        timeout_seconds=int(REQUEST_TIMEOUT_SECONDS),
        max_request_starts=MAX_REQUEST_STARTS,
        requests_started=provider.request_starts,
        responses_received=provider.responses_received,
        retries=0,
        failover=0,
        automatic_continuation_disabled=True,
        tool_execution_count=0,
        turns=tuple(provider.turn_receipts),
        function_linkage_passed=provider.function_linkage_passed,
        terminal_action=result.terminal_action,
        citations_valid=result.citations_valid,
        truth_compatible=result.truth_compatible,
        failed_safe=result.failed_safe,
        final_status=_final_status(result, provider.function_linkage_passed),
    )


async def run_controlled_hydrogen_canary(
    provider: HydrogenCanaryProvider,
) -> HydrogenCanaryReport:
    result = await run_frozen_scenario(
        provider,
        controlled_canary_scenario(),
        corpus_id="reclaimrail-phase17b-controlled-canary",
        max_requests=MAX_REQUEST_STARTS,
    )
    return build_canary_report(provider, result)


def sanitized_report_json(report: HydrogenCanaryReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
