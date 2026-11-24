"""Isolated, bounded smoke-test contract for explicitly allowlisted Gemini models."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

from google import genai
from google.genai import types as genai_types
from pydantic import ValidationError

from app.services.recovery_investigation_tools import CaseToolArguments, public_tool_catalog

GEMINI_38_KEY_NAME: Final = "RECLAIMRAIL_GEMINI_38_API_KEY"
GEMINI_38_MODEL: Final = "gemini-3.8-flash"
GEMINI_4_HYDROGEN_MODEL: Final = "gemini-4-hydrogen"
GEMINI_38_TIMEOUT_SECONDS: Final = 60.0
GEMINI_4_HYDROGEN_TIMEOUT_SECONDS: Final = 120.0
GEMINI_38_CASE_ID: Final = "00000000-0000-4000-8000-000000000038"
GEMINI_38_FORCED_TOOL: Final = "get_truth_snapshot"
_MODEL_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_REASON_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_RATE_HEADERS: Final = {
    "retry-after": "retry_after_seconds",
    "x-ratelimit-limit-requests": "request_limit",
    "x-ratelimit-remaining-requests": "request_remaining",
    "x-ratelimit-limit-tokens": "token_limit",
    "x-ratelimit-remaining-tokens": "token_remaining",
}


class Gemini38KeyMissingError(RuntimeError):
    """Raised without reading or exposing any historical Gemini credential."""


class _Models(Protocol):
    async def get(self, *, model: str) -> object: ...


class _Interactions(Protocol):
    async def create(self, **kwargs: object) -> object: ...


class _AsyncClient(Protocol):
    models: _Models
    interactions: _Interactions

    async def aclose(self) -> None: ...


class _Client(Protocol):
    aio: _AsyncClient

    def close(self) -> None: ...


ClientFactory = Callable[[str, float], _Client]


@dataclass(frozen=True, slots=True)
class GeminiSmokeModel:
    model_name: str
    thinking_level: Literal["low"]
    timeout_seconds: float
    plain_max_output_tokens: int
    forced_max_output_tokens: int
    include_metadata_request: bool


GEMINI_SMOKE_MODELS: Final = {
    GEMINI_38_MODEL: GeminiSmokeModel(
        model_name=GEMINI_38_MODEL,
        thinking_level="low",
        timeout_seconds=GEMINI_38_TIMEOUT_SECONDS,
        plain_max_output_tokens=16,
        forced_max_output_tokens=256,
        include_metadata_request=True,
    ),
    GEMINI_4_HYDROGEN_MODEL: GeminiSmokeModel(
        model_name=GEMINI_4_HYDROGEN_MODEL,
        thinking_level="low",
        timeout_seconds=GEMINI_4_HYDROGEN_TIMEOUT_SECONDS,
        plain_max_output_tokens=256,
        forced_max_output_tokens=256,
        include_metadata_request=False,
    ),
}


@dataclass(frozen=True, slots=True)
class GeminiSmokeReceipt:
    request_kind: Literal["model_metadata", "plain", "forced_function"]
    outcome: Literal["succeeded", "failed_safe"]
    http_status: int | None
    provider_category: str | None
    provider_reason: str | None
    latency_ms: float
    requested_model: str
    returned_model: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    quota: dict[str, int] | None = None
    available: bool | None = None
    plain_exact_ok: bool | None = None
    function_name: str | None = None
    arguments_valid: bool | None = None
    automatic_function_execution_disabled: bool = True
    transport_attempts: int = 1


def load_isolated_key(env_file: Path) -> str:
    """Return only the new isolated key, failing closed without exposing its value."""

    configured = os.environ.get(GEMINI_38_KEY_NAME)
    if configured is None and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{GEMINI_38_KEY_NAME}="):
                configured = line.partition("=")[2]
    if configured is None or not configured.strip():
        raise Gemini38KeyMissingError(f"{GEMINI_38_KEY_NAME} is missing or empty")
    return configured.strip()


def _portable_schema(value: object) -> object:
    allowed = {"type", "properties", "required", "items", "enum", "description"}
    if isinstance(value, Mapping):
        return {str(key): _portable_schema(item) for key, item in value.items() if key in allowed}
    if isinstance(value, list):
        return [_portable_schema(item) for item in value]
    return value


def resolve_smoke_model(model_name: str) -> GeminiSmokeModel:
    try:
        return GEMINI_SMOKE_MODELS[model_name]
    except KeyError:
        raise ValueError("Gemini smoke model is not allowlisted") from None


def sanitize_model_list_entry(model: object) -> dict[str, object]:
    """Sanitize current SDK model metadata without retaining arbitrary provider fields."""

    model_id = _normalized_model(getattr(model, "name", None))
    if model_id is None:
        raise ValueError("Gemini model-list entry has an invalid model ID")
    item: dict[str, object] = {"model_id": model_id}
    display_name = getattr(model, "display_name", None)
    if isinstance(display_name, str) and display_name.strip():
        item["display_name"] = display_name.strip()
    supported_actions = getattr(model, "supported_actions", None)
    if isinstance(supported_actions, list):
        item["supported_actions"] = sorted(
            action
            for action in supported_actions
            if isinstance(action, str) and _MODEL_PATTERN.fullmatch(action)
        )
    for field in ("input_token_limit", "output_token_limit"):
        parsed = _integer(getattr(model, field, None))
        if parsed is not None:
            item[field] = parsed
    return item


def gemini_tool_declarations() -> list[dict[str, object]]:
    declarations: list[dict[str, object]] = []
    for item in public_tool_catalog():
        if item.get("read_only") is not True:
            raise RuntimeError("Gemini 3.8 smoke declarations must remain read-only")
        declarations.append(
            {
                "type": "function",
                "name": item["name"],
                "description": item["description"],
                "parameters": _portable_schema(item["input_schema"]),
            }
        )
    return declarations


def plain_interaction_request(model_name: str = GEMINI_38_MODEL) -> dict[str, object]:
    model = resolve_smoke_model(model_name)
    return {
        "model": model.model_name,
        "input": 'Reply with exactly "OK" and no other text.',
        "store": False,
        "generation_config": {
            "max_output_tokens": model.plain_max_output_tokens,
            "thinking_level": model.thinking_level,
        },
        "timeout": model.timeout_seconds,
        "automatic_continuation": False,
    }


def forced_function_interaction_request(model_name: str = GEMINI_38_MODEL) -> dict[str, object]:
    model = resolve_smoke_model(model_name)
    return {
        "model": model.model_name,
        "input": (
            f"Call {GEMINI_38_FORCED_TOOL} exactly once with case_id {GEMINI_38_CASE_ID}. "
            "Do not execute any function and do not return a final answer."
        ),
        "system_instruction": (
            "This is a controlled synthetic read-only smoke test. Select one declared function. "
            "Never execute a function or request a function result."
        ),
        "tools": gemini_tool_declarations(),
        "store": False,
        "generation_config": {
            "max_output_tokens": model.forced_max_output_tokens,
            "thinking_level": model.thinking_level,
            "tool_choice": {
                "allowed_tools": {
                    "mode": "any",
                    "tools": [GEMINI_38_FORCED_TOOL],
                }
            },
        },
        "timeout": model.timeout_seconds,
        "automatic_continuation": False,
    }


def _default_client_factory(api_key: str, timeout_seconds: float) -> _Client:
    return genai.Client(  # type: ignore[return-value]
        api_key=api_key,
        http_options=genai_types.HttpOptions(
            api_version="v1beta",
            timeout=int(timeout_seconds * 1000),
            retry_options=genai_types.HttpRetryOptions(attempts=1),
        ),
    )


def _normalized_model(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.removeprefix("models/").strip()
    return candidate if _MODEL_PATTERN.fullmatch(candidate) else None


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _headers(error: BaseException) -> Mapping[str, object]:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    return headers if isinstance(headers, Mapping) else {}


def _quota(error: BaseException) -> dict[str, int] | None:
    safe: dict[str, int] = {}
    headers = {str(key).casefold(): value for key, value in _headers(error).items()}
    for header, field in _SAFE_RATE_HEADERS.items():
        parsed = _integer(headers.get(header))
        if parsed is not None:
            safe[field] = parsed
    return safe or None


def _provider_failure(error: BaseException) -> tuple[int | None, str, str | None]:
    status = _integer(getattr(error, "status_code", None))
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return status, "timeout", "TIMEOUT"
    categories = {
        400: "invalid_request",
        401: "authentication",
        403: "access_denied",
        404: "model_unavailable",
        429: "quota_exhausted",
        503: "provider_unavailable",
    }
    category = categories.get(status) if status is not None else None
    if category is None:
        category = (
            "provider_unavailable"
            if status is not None and 500 <= status <= 599
            else "provider_error"
        )
    reason: str | None = None
    raw_reason = getattr(error, "reason", None) or getattr(error, "code", None)
    if isinstance(raw_reason, str):
        candidate = raw_reason.upper().replace("-", "_")
        if _SAFE_REASON_PATTERN.fullmatch(candidate):
            reason = candidate
    return status, category, reason


def _usage(response: object) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    return (
        _integer(getattr(usage, "total_input_tokens", None)),
        _integer(getattr(usage, "total_output_tokens", None)),
        _integer(getattr(usage, "total_thought_tokens", None)),
    )


def _steps(response: object) -> list[object]:
    steps = getattr(response, "steps", None)
    if not isinstance(steps, list):
        raise ValueError("Gemini Interactions response did not contain typed steps")
    return steps


def _function_calls(response: object) -> list[object]:
    return [step for step in _steps(response) if getattr(step, "type", None) == "function_call"]


async def _one_call(
    operation: Callable[[], Awaitable[object]],
    timeout_seconds: float,
) -> tuple[object | None, BaseException | None, float]:
    started = time.monotonic_ns()
    try:
        async with asyncio.timeout(timeout_seconds):
            return await operation(), None, round((time.monotonic_ns() - started) / 1_000_000, 3)
    except Exception as error:  # noqa: BLE001 - sanitized provider boundary
        return None, error, round((time.monotonic_ns() - started) / 1_000_000, 3)


async def run_smoke_request(
    api_key: str,
    kind: Literal["model_metadata", "plain", "forced_function"],
    *,
    model_name: str = GEMINI_38_MODEL,
    client_factory: ClientFactory = _default_client_factory,
) -> GeminiSmokeReceipt:
    model = resolve_smoke_model(model_name)
    if kind == "model_metadata" and not model.include_metadata_request:
        raise ValueError("This smoke model does not authorize a metadata request")
    client = client_factory(api_key, model.timeout_seconds)
    async_client = client.aio
    try:
        if kind == "model_metadata":
            response, error, latency = await _one_call(
                lambda: async_client.models.get(model=model.model_name),
                model.timeout_seconds,
            )
        else:
            request = (
                plain_interaction_request(model.model_name)
                if kind == "plain"
                else forced_function_interaction_request(model.model_name)
            )
            response, error, latency = await _one_call(
                lambda: async_client.interactions.create(**request), model.timeout_seconds
            )
        if error is not None:
            status, category, reason = _provider_failure(error)
            return GeminiSmokeReceipt(
                request_kind=kind,
                outcome="failed_safe",
                http_status=status,
                provider_category=category,
                provider_reason=reason,
                latency_ms=latency,
                requested_model=model.model_name,
                returned_model=None,
                quota=_quota(error),
                available=False if kind == "model_metadata" else None,
            )
        if response is None:
            raise AssertionError("Provider boundary returned neither response nor error")
        if kind == "model_metadata":
            returned = _normalized_model(getattr(response, "name", None))
            available = returned == model.model_name
            return GeminiSmokeReceipt(
                request_kind=kind,
                outcome="succeeded" if available else "failed_safe",
                http_status=200,
                provider_category=None if available else "model_unavailable",
                provider_reason=None,
                latency_ms=latency,
                requested_model=model.model_name,
                returned_model=returned,
                available=available,
            )
        returned = _normalized_model(getattr(response, "model", None))
        input_tokens, output_tokens, thinking_tokens = _usage(response)
        if kind == "plain":
            try:
                no_calls = not _function_calls(response)
                exact_ok = no_calls and getattr(response, "output_text", None) == "OK"
            except ValueError:
                exact_ok = False
            return GeminiSmokeReceipt(
                request_kind=kind,
                outcome="succeeded" if exact_ok else "failed_safe",
                http_status=200,
                provider_category=None if exact_ok else "malformed_response",
                provider_reason=None,
                latency_ms=latency,
                requested_model=model.model_name,
                returned_model=returned,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking_tokens,
                plain_exact_ok=exact_ok,
            )
        try:
            calls = _function_calls(response)
            if len(calls) != 1:
                raise ValueError("Gemini must return exactly one function call")
            call = calls[0]
            name = getattr(call, "name", None)
            arguments = getattr(call, "arguments", None)
            if name != GEMINI_38_FORCED_TOOL or not isinstance(arguments, dict):
                raise ValueError("Gemini returned an unknown function call")
            parsed = CaseToolArguments.model_validate(arguments)
            valid = str(parsed.case_id) == GEMINI_38_CASE_ID
        except (TypeError, ValueError, ValidationError):
            name = None
            valid = False
        return GeminiSmokeReceipt(
            request_kind=kind,
            outcome="succeeded" if valid else "failed_safe",
            http_status=200,
            provider_category=None if valid else "malformed_response",
            provider_reason=None,
            latency_ms=latency,
            requested_model=model.model_name,
            returned_model=returned,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            function_name=name
            if isinstance(name, str) and _MODEL_PATTERN.fullmatch(name)
            else None,
            arguments_valid=valid,
        )
    finally:
        await async_client.aclose()
        client.close()


Gemini38Receipt = GeminiSmokeReceipt
gemini38_tool_declarations = gemini_tool_declarations


def sanitized_receipt(receipt: GeminiSmokeReceipt) -> dict[str, object]:
    return asdict(receipt)
