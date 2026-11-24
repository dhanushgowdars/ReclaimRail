"""Bounded Groq adapter; it returns local function calls and never executes them."""
# ruff: noqa: E501

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Final

import httpx2

from app.core.config import Settings
from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.integrations.gemini.evidence_investigator import (
    _ABSTAIN_ARGUMENT_SCHEMA,
    _ABSTAIN_FUNCTION_NAME,
    _COMPLETE_ARGUMENT_SCHEMA,
    _COMPLETE_FUNCTION_NAME,
    INVESTIGATOR_SYSTEM_INSTRUCTION,
    _provider_function_schema,
)
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    EvidenceInvestigatorProviderReason,
    EvidenceInvestigatorRateLimitCategory,
    EvidenceInvestigatorRateLimitMetadata,
)
from app.services.recovery_investigation_tools import CaseToolArguments, public_tool_catalog

GROQ_BASE_URL: Final = "https://api.groq.com/openai/v1"
GROQ_EVALUATION_PROMPT_VERSION: Final = "groq-evaluation-v3-post-corpus-tuning"
GROQ_EVALUATION_INSTRUCTION: Final = INVESTIGATOR_SYSTEM_INSTRUCTION + (
    "\nChoose exactly one declared function; never call a function named json. "
    "Emit one complete, valid JSON argument object matching that function's schema. "
    "Abstain when required evidence is missing or unresolved. "
    "Use the verified-webhook evidence tool when payment authorization state is in question."
)
GROQ_FUNCTION_CALLING_ALLOWLIST: Final = frozenset({"openai/gpt-oss-120b"})
_OPAQUE_TOOL_CALL_ID: Final = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_DURATION: Final = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s|m|h)?$")


@dataclass(frozen=True, slots=True)
class _GroqToolCall:
    call_id: str
    tool_name: str
    turn: InvestigatorTurn
    assistant_message: dict[str, object]


@dataclass(slots=True)
class _Conversation:
    messages: list[dict[str, object]]
    pending_call: _GroqToolCall | None = None
    observation_count: int = 0
    historical_tool_names: list[str] = field(default_factory=list)


def _tools(request: dict[str, object]) -> list[dict[str, object]]:
    catalog = request.get("tools")
    authoritative = {tool["name"]: tool for tool in public_tool_catalog()}
    if not isinstance(catalog, (tuple, list)) or not catalog:
        raise ValueError("Investigator request requires read-only tools")
    definitions: list[dict[str, object]] = []
    for item in catalog:
        if not isinstance(item, dict) or item.get("read_only") is not True:
            raise ValueError("Investigator tool declaration failed the read-only contract")
        name = item.get("name")
        if not isinstance(name, str) or authoritative.get(name) != item:
            raise ValueError("Investigator tool declaration is not authoritative")
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": item["description"]
                    + (
                        " Use this read-only function when verifying payment authorization state."
                        if name == "get_verified_webhooks"
                        else ""
                    ),
                    "parameters": _provider_function_schema(item["input_schema"]),
                },
            }
        )
    definitions.extend(
        [
            {
                "type": "function",
                "function": {
                    "name": _COMPLETE_FUNCTION_NAME,
                    "description": "Return the final evidence-linked conclusion.",
                    "parameters": _provider_function_schema(_COMPLETE_ARGUMENT_SCHEMA),
                },
            },
            {
                "type": "function",
                "function": {
                    "name": _ABSTAIN_FUNCTION_NAME,
                    "description": "Abstain when evidence is insufficient or conflicting.",
                    "parameters": _provider_function_schema(_ABSTAIN_ARGUMENT_SCHEMA),
                },
            },
        ]
    )
    return definitions


def _definition_name(definition: dict[str, object]) -> str:
    function = definition.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        raise ValueError("Groq function declaration is malformed")
    return str(function["name"])


def _tool_call_from_response(call: object, allowed: set[str]) -> _GroqToolCall:
    if not isinstance(call, dict):
        raise ValueError("Groq function call is not an object")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not _OPAQUE_TOOL_CALL_ID.fullmatch(call_id):
        raise ValueError("Groq function call ID is missing or invalid")
    function = call.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        raise ValueError("Groq function call is malformed")
    raw_arguments = function.get("arguments")
    if not isinstance(raw_arguments, str):
        raise ValueError("Groq function arguments must be JSON text")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ValueError("Groq function arguments are invalid JSON") from error
    if not isinstance(arguments, dict):
        raise ValueError("Groq function arguments must be an object")
    name = function["name"]
    assistant_message: dict[str, object] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": raw_arguments},
            }
        ],
    }
    evidence_tools = {str(tool["name"]) for tool in public_tool_catalog()}
    if name in allowed and name in evidence_tools:
        # Every public evidence function has the exact, strict CaseToolArguments contract.
        CaseToolArguments.model_validate(arguments)
        return _GroqToolCall(
            call_id=call_id,
            tool_name=name,
            turn=InvestigatorTurn(
                action=InvestigationTurnAction.CALL_TOOL, tool_name=name, tool_arguments=arguments
            ),
            assistant_message=assistant_message,
        )
    if name == _COMPLETE_FUNCTION_NAME and name in allowed:
        return _GroqToolCall(
            call_id=call_id,
            tool_name=name,
            turn=InvestigatorTurn.model_validate(
                {**arguments, "action": InvestigationTurnAction.COMPLETE}
            ),
            assistant_message=assistant_message,
        )
    if name == _ABSTAIN_FUNCTION_NAME and name in allowed:
        return _GroqToolCall(
            call_id=call_id,
            tool_name=name,
            turn=InvestigatorTurn.model_validate(
                {**arguments, "action": InvestigationTurnAction.ABSTAIN}
            ),
            assistant_message=assistant_message,
        )
    raise ValueError("Groq requested an unknown investigator function")


def _turn_from_tool_call(call: object, allowed: set[str]) -> InvestigatorTurn:
    """Compatibility boundary used by the strict response parser and preflight."""
    return _tool_call_from_response(call, allowed).turn


def _number(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    parsed = int(value)
    return parsed if 0 <= parsed <= 10**12 else None


def _seconds(value: str | None) -> float | None:
    if value is None:
        return None
    match = _DURATION.fullmatch(value.strip())
    if match is None:
        return None
    amount = float(match["value"])
    multiplier = {None: 1.0, "ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[match["unit"]]
    seconds = amount * multiplier
    return seconds if 0 <= seconds <= 86_400 else None


def _rate_limit_metadata(headers: httpx2.Headers) -> EvidenceInvestigatorRateLimitMetadata:
    request_remaining = _number(headers.get("x-ratelimit-remaining-requests"))
    token_remaining = _number(headers.get("x-ratelimit-remaining-tokens"))
    if request_remaining == 0 and token_remaining == 0:
        category = EvidenceInvestigatorRateLimitCategory.REQUEST_AND_TOKEN
    elif request_remaining == 0:
        category = EvidenceInvestigatorRateLimitCategory.REQUEST
    elif token_remaining == 0:
        category = EvidenceInvestigatorRateLimitCategory.TOKEN
    else:
        category = EvidenceInvestigatorRateLimitCategory.UNKNOWN
    return EvidenceInvestigatorRateLimitMetadata(
        category=category,
        request_limit=_number(headers.get("x-ratelimit-limit-requests")),
        request_remaining=request_remaining,
        token_limit=_number(headers.get("x-ratelimit-limit-tokens")),
        token_remaining=token_remaining,
        request_reset_seconds=_seconds(headers.get("x-ratelimit-reset-requests")),
        token_reset_seconds=_seconds(headers.get("x-ratelimit-reset-tokens")),
        retry_after_seconds=_seconds(headers.get("retry-after")),
    )


def _error(
    error: Exception,
    status_code: int | None = None,
    headers: httpx2.Headers | None = None,
) -> EvidenceInvestigatorProviderError:
    if isinstance(error, (httpx2.TimeoutException, TimeoutError)):
        kind = EvidenceInvestigatorFailureKind.TIMEOUT
    elif isinstance(error, httpx2.RequestError):
        kind = EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER
    elif status_code in {401, 403}:
        kind = EvidenceInvestigatorFailureKind.ACCESS_DENIED
    elif status_code == 429:
        kind = EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED
    elif status_code is not None and 500 <= status_code <= 599:
        kind = EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER
    elif status_code is not None and 400 <= status_code <= 499:
        kind = EvidenceInvestigatorFailureKind.PROVIDER_REJECTED
    else:
        kind = EvidenceInvestigatorFailureKind.UNKNOWN_PROVIDER
    reason = (
        EvidenceInvestigatorProviderReason.CREDENTIAL_REJECTED
        if status_code in {401, 403}
        else None
    )
    return EvidenceInvestigatorProviderError(
        "Groq evidence investigation failed safely",
        kind=kind,
        retryable=False,
        status_code=status_code,
        reason_code=reason,
        rate_limit_metadata=(
            _rate_limit_metadata(headers) if status_code == 429 and headers is not None else None
        ),
    )


class GroqEvidenceInvestigator:
    provider_name = "groq"
    base_url = GROQ_BASE_URL
    model_allowlist = GROQ_FUNCTION_CALLING_ALLOWLIST

    @staticmethod
    def _quota_from_headers(headers: httpx2.Headers) -> EvidenceInvestigatorRateLimitMetadata:
        return _rate_limit_metadata(headers)

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        max_output_tokens: int = 4096,
        request_timeout_seconds: float = 60.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise EvidenceInvestigatorProviderError(
                "Groq investigator key is not configured",
                kind=EvidenceInvestigatorFailureKind.CONFIGURATION,
                retryable=False,
                reason_code=EvidenceInvestigatorProviderReason.KEY_MISSING,
            )
        if not model_name.strip():
            raise EvidenceInvestigatorProviderError(
                "Groq investigator model is not configured",
                kind=EvidenceInvestigatorFailureKind.CONFIGURATION,
                retryable=False,
                reason_code=EvidenceInvestigatorProviderReason.MODEL_MISSING,
            )
        if model_name not in self.model_allowlist:
            raise ValueError(
                "Configured Groq model is not in the reviewed function-calling allowlist"
            )
        self._api_key, self.model_name = api_key.strip(), model_name.strip()
        self._max_output_tokens, self._timeout_seconds, self._transport = (
            max_output_tokens,
            request_timeout_seconds,
            transport,
        )
        self._conversations: dict[str, _Conversation] = {}
        # Evaluation-only diagnostic seam; callers must sanitize before persistence.
        self.last_diagnostic_details: dict[str, object] | None = None
        self._retry_fingerprint: str | None = None

    @staticmethod
    def _conversation_key(request: dict[str, object]) -> str:
        benchmark = request.get("benchmark")
        if isinstance(benchmark, dict) and isinstance(benchmark.get("scenario_id"), str):
            return f"benchmark:{benchmark['scenario_id']}"
        case = request.get("case")
        if isinstance(case, dict) and isinstance(case.get("id"), str):
            return f"case:{case['id']}"
        raise ValueError("Investigator request lacks a stable conversation identifier")

    @staticmethod
    def _initial_messages(request: dict[str, object]) -> list[dict[str, object]]:
        initial_request = {**request, "observations": []}
        return [
            {"role": "system", "content": GROQ_EVALUATION_INSTRUCTION},
            {
                "role": "user",
                "content": "Investigate this recovery case without taking action:\n"
                + json.dumps(initial_request, sort_keys=True, separators=(",", ":"), default=str),
            },
        ]

    @staticmethod
    def _next_observation(
        request: dict[str, object], conversation: _Conversation
    ) -> dict[str, object]:
        observations = request.get("observations")
        if (
            not isinstance(observations, list)
            or len(observations) != conversation.observation_count + 1
        ):
            raise ValueError("Groq tool result is missing, duplicate, or out of sequence")
        observation = observations[-1]
        pending = conversation.pending_call
        if not isinstance(observation, dict) or pending is None:
            raise ValueError("Groq tool result has no pending function call")
        if observation.get("tool") != pending.tool_name:
            raise ValueError("Groq tool result does not match the pending function")
        if not isinstance(observation.get("outcome"), str):
            raise ValueError("Groq tool result is malformed")
        return observation

    def _messages(self, request: dict[str, object]) -> tuple[str, _Conversation]:
        key = self._conversation_key(request)
        conversation = self._conversations.get(key)
        observations = request.get("observations")
        if conversation is None:
            if observations not in ([], ()):
                raise ValueError("Groq conversation cannot begin with a tool result")
            conversation = _Conversation(messages=self._initial_messages(request))
            self._conversations[key] = conversation
            return key, conversation
        observation = self._next_observation(request, conversation)
        pending = conversation.pending_call
        assert pending is not None
        conversation.messages.append(pending.assistant_message)
        conversation.messages.append(self._tool_result_message(pending, observation))
        if pending.tool_name not in conversation.historical_tool_names:
            conversation.historical_tool_names.append(pending.tool_name)
        conversation.observation_count += 1
        conversation.pending_call = None
        return key, conversation

    @staticmethod
    def _tool_result_message(
        pending: _GroqToolCall, observation: dict[str, object]
    ) -> dict[str, object]:
        return {
            "role": "tool",
            "tool_call_id": pending.call_id,
            "content": json.dumps(observation, sort_keys=True, separators=(",", ":"), default=str),
        }

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        key: str | None = None
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True, default=str).encode()
        ).hexdigest()
        self.last_diagnostic_details = None
        try:
            all_tool_definitions = _tools(request)
            definitions_by_name = {
                _definition_name(definition): definition for definition in all_tool_definitions
            }
            forced = request.get("_evaluation_forced_function_names")
            forced_names: tuple[str, ...] | None = None
            if forced is not None:
                if (
                    not isinstance(forced, tuple)
                    or not 1 <= len(forced) <= 2
                    or not all(isinstance(name, str) for name in forced)
                ):
                    raise ValueError("Evaluation forced functions are invalid")
                forced_names = forced
                if any(name not in definitions_by_name for name in forced_names):
                    raise ValueError("Evaluation forced function is not allowlisted")
            key = self._conversation_key(request)
            if self._retry_fingerprint == fingerprint and key in self._conversations:
                conversation = self._conversations[key]
            else:
                _, conversation = self._messages(request)
            self._retry_fingerprint = None
            if forced_names is None:
                tool_definitions = all_tool_definitions
                allowed = set(definitions_by_name)
            else:
                wire_names = tuple(
                    dict.fromkeys((*conversation.historical_tool_names, *forced_names))
                )
                tool_definitions = [definitions_by_name[name] for name in wire_names]
                # Historical calls exist only for provider transport continuity. They are not
                # valid responses for the current bounded evaluation state.
                allowed = set(forced_names)
            payload = {
                "model": self.model_name,
                "messages": conversation.messages,
                "tools": tool_definitions,
                "tool_choice": (
                    {
                        "type": "function",
                        "function": {"name": forced_names[0]},
                    }
                    if forced_names is not None and len(forced_names) == 1
                    else "required"
                ),
                "parallel_tool_calls": False,
                "max_completion_tokens": self._max_output_tokens,
                "temperature": 0,
            }
            self.last_diagnostic_details = {
                "tool_declarations_sha256": hashlib.sha256(
                    json.dumps(tool_definitions, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "tool_choice": payload["tool_choice"],
                "parallel_tool_calls": False,
                "message_structure": [
                    {
                        "role": message.get("role"),
                        "tool_call_id": message.get("tool_call_id"),
                        "tool_call_ids": [
                            call.get("id") for call in calls if isinstance(call, dict)
                        ]
                        if isinstance((calls := message.get("tool_calls")), list)
                        else [],
                        "content_length": len(str(message.get("content") or "")),
                    }
                    for message in conversation.messages
                ],
            }
            async with httpx2.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx2.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
            if response.status_code >= 400:
                provider_error: dict[str, object] = {}
                try:
                    parsed = response.json()
                    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                        provider_error = parsed["error"]
                except (ValueError, TypeError):
                    pass
                assert self.last_diagnostic_details is not None
                self.last_diagnostic_details.update(
                    {
                        "provider_error_code_raw": provider_error.get("code"),
                        "provider_error_type_raw": provider_error.get("type"),
                        "provider_error_message_raw": provider_error.get("message"),
                        "failed_generation_raw": provider_error.get("failed_generation"),
                        "x_request_id": response.headers.get("x-request-id"),
                    }
                )
                raise _error(RuntimeError("http failure"), response.status_code, response.headers)
            body = response.json()
            choices = body.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
            ):
                raise ValueError("Groq returned an ambiguous response")
            message = choices[0].get("message")
            if not isinstance(message, dict) or message.get("content") not in (None, ""):
                raise ValueError("Groq returned free text")
            calls = message.get("tool_calls")
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("Groq must return exactly one local function call")
            tool_call = _tool_call_from_response(calls[0], allowed)
            self.last_diagnostic_details = {
                **(self.last_diagnostic_details or {}),
                "turn_type": tool_call.turn.action.value,
                "call_id": tool_call.call_id,
                "tool_name": tool_call.tool_name,
                "arguments": tool_call.turn.tool_arguments,
                "finish_reason": "tool_calls",
            }
            if tool_call.turn.action is InvestigationTurnAction.CALL_TOOL:
                conversation.pending_call = tool_call
            else:
                self._conversations.pop(key, None)
            self._retry_fingerprint = None
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            quota = self._quota_from_headers(response.headers)
            quota_metadata = (
                quota.as_dict()
                if any(
                    value is not None for key, value in quota.as_dict().items() if key != "category"
                )
                else None
            )
            return InvestigatorProviderResponse(
                turn=tool_call.turn,
                model_name=body.get("model")
                if isinstance(body.get("model"), str)
                else self.model_name,
                model_version=None,
                input_token_count=usage.get("prompt_tokens")
                if isinstance(usage.get("prompt_tokens"), int)
                else None,
                output_token_count=usage.get("completion_tokens")
                if isinstance(usage.get("completion_tokens"), int)
                else None,
                provider=self.provider_name,
                quota_metadata=quota_metadata,
            )
        except EvidenceInvestigatorProviderError as error:
            if isinstance(self.last_diagnostic_details, dict) and (
                self.last_diagnostic_details.get("provider_error_code_raw") == "tool_use_failed"
                or error.kind
                in {
                    EvidenceInvestigatorFailureKind.TIMEOUT,
                    EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
                }
            ):
                self._retry_fingerprint = fingerprint
            self.last_diagnostic_details = {
                **(self.last_diagnostic_details or {}),
                "turn_type": "provider_error",
                "finish_reason": "provider_error",
                "local_validation_failure_reason_code": "provider_boundary_error",
            }
            if isinstance(error, EvidenceInvestigatorProviderError):
                self.last_diagnostic_details.update(
                    {
                        "http_status": error.status_code,
                        "provider_error_type": error.kind.value,
                        "provider_error_code": (
                            error.reason_code.value if error.reason_code is not None else None
                        ),
                        "scrubbed_error_message": str(error),
                    }
                )
            if key is not None and self._retry_fingerprint is None:
                self._conversations.pop(key, None)
            raise
        except (ValueError, json.JSONDecodeError):
            self.last_diagnostic_details = {
                "turn_type": "malformed",
                "finish_reason": "malformed_output",
                "local_validation_failure_reason_code": "malformed_function_response",
                "scrubbed_error_message": "Groq returned invalid investigator output",
            }
            if key is not None:
                self._conversations.pop(key, None)
            raise EvidenceInvestigatorProviderError(
                "Groq returned invalid investigator output",
                kind=EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE,
                retryable=False,
            ) from None
        except Exception as error:
            self._retry_fingerprint = fingerprint
            raise _error(error) from None


def create_groq_evidence_investigator(settings: Settings) -> GroqEvidenceInvestigator | None:
    if (
        not settings.recovery_investigator_shadow_enabled
        or settings.groq_api_key is None
        or not settings.groq_model_name
    ):
        return None
    key = settings.groq_api_key.get_secret_value().strip()
    return (
        GroqEvidenceInvestigator(
            api_key=key,
            model_name=settings.groq_model_name,
            max_output_tokens=settings.groq_max_output_tokens,
            request_timeout_seconds=settings.groq_request_timeout_seconds,
        )
        if key
        else None
    )
