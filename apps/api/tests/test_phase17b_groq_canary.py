import json
from pathlib import Path

import httpx2
import pytest

from app.evaluation.phase17b_groq_canary import run_groq_canary
from app.evaluation.phase17b_groq_governor import GovernedEvaluationProvider, GroqEvaluationGovernor
from app.integrations.groq.evidence_investigator import GroqEvidenceInvestigator
from app.integrations.investigator import EvidenceInvestigatorProviderError


def _response(name: str, arguments: dict[str, object], call_id: str) -> dict[str, object]:
    return {
        "model": "openai/gpt-oss-120b",
        "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ],
    }


@pytest.mark.asyncio
async def test_controlled_synthetic_canary_completes_three_correlated_turns() -> None:
    now = 0.0

    def clock() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    messages = [
        ("get_truth_snapshot", {"case_id": "00000000-0000-4000-8000-000000000018"}),
        ("get_verified_webhooks", {"case_id": "00000000-0000-4000-8000-000000000018"}),
        (
            "complete_investigation",
            {
                "summary": "Synthetic evidence is complete.",
                "evidence_ids": ["canary-evidence-1", "canary-evidence-2"],
            },
        ),
    ]
    seen: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        name, arguments = messages.pop(0)
        return httpx2.Response(
            200,
            headers={"x-ratelimit-remaining-requests": "29"},
            json={
                "model": "openai/gpt-oss-120b",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "opaque_" + str(len(seen)),
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ],
                        }
                    }
                ],
            },
        )

    groq = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    report = await run_groq_canary(
        GovernedEvaluationProvider(groq, GroqEvaluationGovernor(clock, sleep))
    )
    assert report.request_count == 3
    assert report.first_correlation_valid and report.second_correlation_valid
    assert report.terminal_schema_valid and report.tool_execution_count == 0
    assert [item["tool_choice"] for item in seen[:2]] == [
        {"type": "function", "function": {"name": "get_truth_snapshot"}},
        {"type": "function", "function": {"name": "get_verified_webhooks"}},
    ]
    assert [item["function"]["name"] for item in seen[1]["tools"]] == [
        "get_truth_snapshot",
        "get_verified_webhooks",
    ]
    assert [item["function"]["name"] for item in seen[2]["tools"]] == [
        "get_truth_snapshot",
        "get_verified_webhooks",
        "complete_investigation",
        "abstain_investigation",
    ]
    assert seen[2]["tool_choice"] == "required"
    assert seen[1]["messages"][-1]["role"] == "tool"
    assert seen[1]["messages"][-2]["tool_calls"][0]["id"] == seen[1]["messages"][-1]["tool_call_id"]
    assert (
        seen[1]["messages"][-2]["tool_calls"][0]["function"]["name"]
        == seen[1]["messages"][-1]["name"]
    )
    assert seen[2]["messages"][-1]["tool_call_id"] == "opaque_2"


@pytest.mark.asyncio
async def test_state_two_rejects_historical_tool_as_a_new_response() -> None:
    now = 0.0

    def clock() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    replies = [
        _response("get_truth_snapshot", {"case_id": "00000000-0000-4000-8000-000000000018"}, "one"),
        _response("get_truth_snapshot", {"case_id": "00000000-0000-4000-8000-000000000018"}, "two"),
    ]
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=replies.pop(0))

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(EvidenceInvestigatorProviderError):
        await run_groq_canary(
            GovernedEvaluationProvider(provider, GroqEvaluationGovernor(clock, sleep))
        )
    assert calls == 2


@pytest.mark.asyncio
async def test_canary_rejects_unexpected_third_read_only_function_without_fourth_request() -> None:
    now = 0.0

    def clock() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    replies = [
        _response("get_truth_snapshot", {"case_id": "00000000-0000-4000-8000-000000000018"}, "one"),
        _response(
            "get_verified_webhooks", {"case_id": "00000000-0000-4000-8000-000000000018"}, "two"
        ),
        _response(
            "get_truth_snapshot", {"case_id": "00000000-0000-4000-8000-000000000018"}, "three"
        ),
    ]
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=replies.pop(0))

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(EvidenceInvestigatorProviderError):
        await run_groq_canary(
            GovernedEvaluationProvider(provider, GroqEvaluationGovernor(clock, sleep))
        )
    assert calls == 3


@pytest.mark.asyncio
async def test_canary_rejects_invalid_terminal_schema() -> None:
    now = 0.0

    def clock() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    replies = [
        _response("get_truth_snapshot", {"case_id": "00000000-0000-4000-8000-000000000018"}, "one"),
        _response(
            "get_verified_webhooks", {"case_id": "00000000-0000-4000-8000-000000000018"}, "two"
        ),
        _response("complete_investigation", {"summary": "missing citations"}, "three"),
    ]

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=replies.pop(0))

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(EvidenceInvestigatorProviderError):
        await run_groq_canary(
            GovernedEvaluationProvider(provider, GroqEvaluationGovernor(clock, sleep))
        )


def test_production_paths_do_not_depend_on_evaluation_canary() -> None:
    api_root = Path(__file__).parents[1] / "app"
    production_paths = [api_root / "workers", api_root / "services", api_root / "api" / "routes"]
    for path in production_paths:
        for source in path.rglob("*.py"):
            assert "phase17b_groq_canary" not in source.read_text(encoding="utf-8")
            assert "run_groq_canary" not in source.read_text(encoding="utf-8")
