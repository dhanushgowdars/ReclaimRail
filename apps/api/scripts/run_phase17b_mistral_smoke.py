"""Owner-gated three-request Mistral evaluation smoke; never executes returned tools."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx2

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.integrations.groq.evidence_investigator import _tools, _turn_from_tool_call  # noqa: E402
from app.services.recovery_investigation_tools import public_tool_catalog  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MODEL = "mistral-large-2512"
CONTINUATION_MODEL = "mistral-medium-latest"
PREVIOUS_SMOKE = ROOT / ".runtime" / "phase17b" / "mistral-smoke-20261123-owner.json"
PREVIOUS_CONTINUATION = (
    ROOT / ".runtime" / "phase17b" / "mistral-medium-smoke-continuation-20261123-owner.json"
)
BASE_URL = "https://api.mistral.ai/v1"
TIMEOUT_SECONDS = 60.0
REQUESTS_PER_SECOND = 1
TOKENS_PER_MINUTE = 250_000
CONTINUATION_TOKENS_PER_MINUTE = 20_000


def _availability(cards: object, target: str) -> str:
    if not isinstance(cards, list):
        raise ValueError("Model-list response is malformed")
    matching = [card for card in cards if isinstance(card, dict) and card.get("id") == target]
    if not matching:
        return "absent_from_model_list"
    capabilities = matching[0].get("capabilities")
    if (
        not isinstance(capabilities, dict)
        or capabilities.get("completion_chat") is not True
        or capabilities.get("function_calling") is not True
    ):
        return "present_but_not_chat_tool_capable"
    return "eligible"


def _key() -> str:
    path = ROOT / "apps" / "api" / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("RECLAIMRAIL_MISTRAL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError("RECLAIMRAIL_MISTRAL_API_KEY is missing")


def _limits(headers: httpx2.Headers) -> dict[str, int]:
    safe: dict[str, int] = {}
    for field in ("x-ratelimit-remaining", "x-ratelimit-limit", "retry-after"):
        value = headers.get(field)
        if value is not None and value.isdigit() and int(value) <= 10**12:
            safe[field] = int(value)
    return safe


def _tool_name(tool: dict[str, object]) -> str | None:
    function = tool.get("function")
    return str(function.get("name")) if isinstance(function, dict) else None


async def run(
    output: Path,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
    continuation: bool = False,
    forced_only: bool = False,
) -> dict[str, object]:
    if forced_only and not continuation:
        raise ValueError("Forced-only mode requires the reviewed medium continuation")
    if output.exists() or output.parent.resolve() != (ROOT / ".runtime" / "phase17b").resolve():
        raise ValueError("A new ignored Phase 17B output path is required")
    key = _key()
    if not key:
        raise ValueError("RECLAIMRAIL_MISTRAL_API_KEY is empty")
    receipts: list[dict[str, object]] = []
    target = CONTINUATION_MODEL if continuation else MODEL
    tpm_limit = CONTINUATION_TOKENS_PER_MINUTE if continuation else TOKENS_PER_MINUTE
    evidence: dict[str, object] = {
        "provider": "mistral",
        "model": target,
        "configured_tpm": tpm_limit,
        "configured_rps": REQUESTS_PER_SECOND,
        "requests": receipts,
    }
    last_start: float | None = None
    latency_ms = 0
    async with httpx2.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx2.Timeout(TIMEOUT_SECONDS),
        transport=transport,
    ) as client:

        async def request(
            method: str, path: str, payload: dict[str, object] | None = None
        ) -> httpx2.Response:
            nonlocal last_start, latency_ms
            if last_start is not None:
                await asyncio.sleep(
                    max(0.0, 1 / REQUESTS_PER_SECOND - (time.monotonic() - last_start))
                )
            last_start = time.monotonic()
            began = last_start
            response = await client.request(method, path, json=payload)
            latency_ms = round((time.monotonic() - began) * 1000)
            return response

        if continuation:
            prior = json.loads(PREVIOUS_SMOKE.read_text(encoding="utf-8"))
            previous_requests = prior.get("requests", [])
            if not isinstance(previous_requests, list) or len(previous_requests) != 1:
                raise ValueError("Previous sanitized model-list evidence is invalid")
            prior_list = previous_requests[0]
            if (
                not isinstance(prior_list, dict)
                or prior_list.get("kind") != "model_list"
                or prior_list.get("status") != 200
            ):
                raise ValueError("Previous model-list request was not confirmed")
            eligible = prior_list.get("chat_tool_models")
            if not isinstance(eligible, list) or target not in eligible:
                raise ValueError("Continuation model was not eligible in prior evidence")
            evidence["target_availability"] = "eligible"
            if forced_only:
                earlier = json.loads(PREVIOUS_CONTINUATION.read_text(encoding="utf-8"))
                earlier_requests = earlier.get("requests", [])
                if (
                    earlier.get("model") != target
                    or earlier.get("target_availability") != "eligible"
                    or not isinstance(earlier_requests, list)
                    or len(earlier_requests) != 1
                    or not isinstance(earlier_requests[0], dict)
                    or earlier_requests[0].get("kind") != "plain"
                ):
                    raise ValueError(
                        "Previous plain request receipt does not authorize forced-only continuation"
                    )
                evidence["previous_plain_status"] = earlier_requests[0].get("status")
        else:
            response = await request("GET", "/models")
            models = response.json() if response.status_code == 200 else {}
            cards = models.get("data", []) if isinstance(models, dict) else []
            status = (
                _availability(cards, target) if response.status_code == 200 else "model_list_failed"
            )
            evidence["target_availability"] = status
            receipts.append(
                {
                    "kind": "model_list",
                    "status": response.status_code,
                    "latency_ms": latency_ms,
                    "limits": _limits(response.headers),
                }
            )
        if evidence["target_availability"] != "eligible":
            evidence["stop_reason"] = "candidate_not_available_for_chat_tools"
        else:
            used_tokens = 0
            for kind, payload in (
                (
                    "plain",
                    {
                        "model": target,
                        "messages": [{"role": "user", "content": "Reply with exactly OK"}],
                        "max_tokens": 8,
                    },
                ),
                (
                    "forced_tool",
                    {
                        "model": target,
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"Call get_truth_snapshot with case_id {uuid4()}. "
                                    "Do not execute any tool."
                                ),
                            }
                        ],
                        "tools": [
                            tool
                            for tool in _tools({"tools": public_tool_catalog()})
                            if _tool_name(tool) == "get_truth_snapshot"
                        ],
                        "tool_choice": {
                            "type": "function",
                            "function": {"name": "get_truth_snapshot"},
                        },
                        "parallel_tool_calls": False,
                        "max_tokens": 128,
                    },
                ),
            ):
                if forced_only and kind == "plain":
                    continue
                estimate = (len(json.dumps(payload, default=str).encode()) + 3) // 4
                max_tokens = payload.get("max_tokens")
                if not isinstance(max_tokens, int):
                    raise ValueError("Smoke request requires an integer output ceiling")
                estimate += max_tokens
                if used_tokens + estimate > tpm_limit:
                    evidence["stop_reason"] = "configured_token_ceiling"
                    break
                response = await request("POST", "/chat/completions", payload)
                body = response.json() if response.status_code == 200 else {}
                usage = body.get("usage", {}) if isinstance(body, dict) else {}
                message = (
                    body.get("choices", [{}])[0].get("message", {})
                    if isinstance(body, dict) and body.get("choices")
                    else {}
                )
                item: dict[str, object] = {
                    "kind": kind,
                    "status": response.status_code,
                    "latency_ms": latency_ms,
                    "limits": _limits(response.headers),
                    "input_tokens": usage.get("prompt_tokens")
                    if isinstance(usage.get("prompt_tokens"), int)
                    else None,
                    "output_tokens": usage.get("completion_tokens")
                    if isinstance(usage.get("completion_tokens"), int)
                    else None,
                }
                if kind == "plain":
                    item["ok_exact"] = message.get("content") == "OK"
                elif response.status_code == 200:
                    calls = message.get("tool_calls") if isinstance(message, dict) else None
                    item["tool_call_count"] = len(calls) if isinstance(calls, list) else 0
                    if isinstance(calls, list) and len(calls) == 1:
                        try:
                            turn = _turn_from_tool_call(calls[0], {"get_truth_snapshot"})
                            item["tool_name"] = turn.tool_name
                            item["arguments_valid"] = True
                        except ValueError:
                            item["arguments_valid"] = False
                receipts.append(item)
                used_tokens += (
                    item["input_tokens"] + item["output_tokens"]
                    if isinstance(item["input_tokens"], int)
                    and isinstance(item["output_tokens"], int)
                    else estimate
                )
                if response.status_code >= 400:
                    evidence["stop_reason"] = "provider_failure"
                    break
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, sort_keys=True)
    return evidence


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 3):
        raise SystemExit("Expected one new ignored output path and optional continuation mode")
    if len(sys.argv) == 3 and sys.argv[2] not in ("--continue-medium", "--forced-only-medium"):
        raise SystemExit("Unsupported continuation mode")
    asyncio.run(
        run(
            Path(sys.argv[1]),
            continuation=len(sys.argv) == 3,
            forced_only=len(sys.argv) == 3 and sys.argv[2] == "--forced-only-medium",
        )
    )
