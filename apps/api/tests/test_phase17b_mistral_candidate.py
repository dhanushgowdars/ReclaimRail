"""Offline Mistral candidate and three-slot smoke contract."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)
from app.integrations.mistral.evidence_investigator import MistralEvidenceInvestigator
from app.services.recovery_investigation_tools import public_tool_catalog
from scripts import run_phase17b_mistral_smoke as smoke

CASE_ID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    ("cards", "expected"),
    [
        ([], "absent_from_model_list"),
        (
            [
                {
                    "id": "mistral-medium-latest",
                    "capabilities": {"completion_chat": True, "function_calling": False},
                }
            ],
            "present_but_not_chat_tool_capable",
        ),
        (
            [
                {
                    "id": "mistral-medium-latest",
                    "capabilities": {"completion_chat": True, "function_calling": True},
                }
            ],
            "eligible",
        ),
    ],
)
def test_model_availability_has_only_closed_states(
    cards: list[dict[str, object]], expected: str
) -> None:
    assert smoke._availability(cards, "mistral-medium-latest") == expected


def _request(observations: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "case": {"id": CASE_ID},
        "objective": "inspect",
        "tools": public_tool_catalog(),
        "observations": observations or [],
    }


@pytest.mark.asyncio
async def test_adapter_correlates_one_read_only_call_without_tool_execution() -> None:
    wire: list[dict[str, object]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        payload = json.loads(req.content)
        wire.append(payload)
        assert req.url.host == "api.mistral.ai"
        assert payload["tool_choice"] == "required"
        assert payload["parallel_tool_calls"] is False
        name = "get_truth_snapshot" if len(wire) == 1 else "abstain_investigation"
        args = {"case_id": CASE_ID} if len(wire) == 1 else {"abstention_reason": "missing evidence"}
        return httpx2.Response(
            200,
            headers={"X-RateLimit-Remaining": "99", "Authorization": "secret"},
            json={
                "model": "mistral-large-2512",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "opaque_1" if len(wire) == 1 else "opaque_2",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        }
                    }
                ],
            },
        )

    provider = MistralEvidenceInvestigator(
        api_key="test-only",
        model_name="mistral-large-2512",
        transport=httpx2.MockTransport(handler),
    )
    first = await provider.next_turn(_request())
    assert first.turn.tool_name == "get_truth_snapshot"
    second = await provider.next_turn(
        _request(
            [
                {
                    "sequence": 1,
                    "tool": "get_truth_snapshot",
                    "outcome": "succeeded",
                    "evidence_ids": ("e1",),
                    "payload": {},
                }
            ]
        )
    )
    assert second.turn.action.value == "abstain"
    assert second.input_token_count == 10 and second.output_token_count == 5
    assert second.quota_metadata == {
        "category": "request",
        "request_remaining": 99,
        "request_limit": None,
        "token_limit": None,
        "token_remaining": None,
        "request_reset_seconds": None,
        "token_reset_seconds": None,
        "retry_after_seconds": None,
    }
    tool_message = wire[1]["messages"][3]
    assert tool_message["name"] == "get_truth_snapshot"
    assert tool_message["tool_call_id"] == "opaque_1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calls",
    [
        [],
        [{"id": "bad", "function": {"name": "unknown", "arguments": "{}"}}],
        [{"id": "one", "function": {"name": "get_truth_snapshot", "arguments": "{"}}],
        [
            {"id": "one", "function": {"name": "get_truth_snapshot", "arguments": "{}"}},
            {"id": "two", "function": {"name": "get_truth_snapshot", "arguments": "{}"}},
        ],
    ],
)
async def test_adapter_fails_closed_on_malformed_unknown_or_multiple_calls(
    calls: list[dict[str, object]],
) -> None:
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            json={
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "choices": [{"message": {"content": None, "tool_calls": calls}}],
            },
        )
    )
    provider = MistralEvidenceInvestigator(
        api_key="test-only", model_name="mistral-large-2512", transport=transport
    )
    with pytest.raises(EvidenceInvestigatorProviderError):
        await provider.next_turn(_request())


@pytest.mark.asyncio
async def test_adapter_maps_provider_quota_failure_without_exposing_body() -> None:
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            429,
            headers={"X-RateLimit-Remaining": "0", "Authorization": "private"},
            json={"error": {"message": "private body"}},
        )
    )
    provider = MistralEvidenceInvestigator(
        api_key="test-only", model_name="mistral-large-2512", transport=transport
    )
    with pytest.raises(EvidenceInvestigatorProviderError) as raised:
        await provider.next_turn(_request())
    assert raised.value.kind is EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED
    assert raised.value.status_code == 429
    assert "private" not in str(raised.value)


@pytest.mark.asyncio
async def test_smoke_uses_three_slots_and_stores_no_secret_or_opaque_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "_key", lambda: "private-test-key")
    output = tmp_path / ".runtime" / "phase17b" / "new.json"
    observed: list[dict[str, object]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        if req.method == "GET":
            return httpx2.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "mistral-large-2512",
                            "capabilities": {"completion_chat": True, "function_calling": True},
                        }
                    ]
                },
            )
        payload = json.loads(req.content)
        observed.append(payload)
        if len(observed) == 1:
            assert "tools" not in payload
            return httpx2.Response(
                200,
                json={
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                    "choices": [{"message": {"content": "OK"}}],
                },
            )
        assert payload["parallel_tool_calls"] is False
        assert payload["tool_choice"]["function"]["name"] == "get_truth_snapshot"
        return httpx2.Response(
            200,
            json={
                "usage": {"prompt_tokens": 9, "completion_tokens": 3},
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "opaque_private",
                                    "function": {
                                        "name": "get_truth_snapshot",
                                        "arguments": json.dumps({"case_id": CASE_ID}),
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    result = await smoke.run(output, transport=httpx2.MockTransport(handler))
    assert len(result["requests"]) == 3
    assert result["target_availability"] == "eligible"
    assert result["requests"][2]["arguments_valid"] is True
    assert result["requests"][2]["tool_name"] == "get_truth_snapshot"
    saved = output.read_text(encoding="utf-8")
    assert "private-test-key" not in saved and "opaque_private" not in saved
    assert "case_id" not in saved and "Reply with exactly OK" not in saved


@pytest.mark.asyncio
async def test_smoke_stops_after_model_list_when_candidate_lacks_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "_key", lambda: "private-test-key")
    requests = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "id": "mistral-large-2512",
                        "capabilities": {"completion_chat": True, "function_calling": False},
                    }
                ]
            },
        )

    output = tmp_path / ".runtime" / "phase17b" / "new.json"
    result = await smoke.run(output, transport=httpx2.MockTransport(handler))
    assert requests == 1
    assert result["stop_reason"] == "candidate_not_available_for_chat_tools"
    assert len(result["requests"]) == 1
    assert result["target_availability"] == "present_but_not_chat_tool_capable"


@pytest.mark.asyncio
async def test_continuation_uses_two_chat_slots_without_model_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "_key", lambda: "private-test-key")
    prior = tmp_path / "prior.json"
    prior.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "kind": "model_list",
                        "status": 200,
                        "chat_tool_models": ["mistral-medium-latest"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke, "PREVIOUS_SMOKE", prior)
    posts = 0

    def handler(req: httpx2.Request) -> httpx2.Response:
        nonlocal posts
        assert req.method == "POST" and req.url.path == "/v1/chat/completions"
        posts += 1
        payload = json.loads(req.content)
        assert payload["model"] == "mistral-medium-latest"
        if posts == 1:
            assert "tools" not in payload
            return httpx2.Response(
                200,
                json={
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    "choices": [{"message": {"content": "OK"}}],
                },
            )
        assert payload["parallel_tool_calls"] is False
        return httpx2.Response(
            200,
            json={
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "opaque-secret",
                                    "function": {
                                        "name": "get_truth_snapshot",
                                        "arguments": json.dumps({"case_id": CASE_ID}),
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    output = tmp_path / ".runtime" / "phase17b" / "medium.json"
    result = await smoke.run(output, transport=httpx2.MockTransport(handler), continuation=True)
    assert posts == 2
    assert result["target_availability"] == "eligible"
    assert [entry["kind"] for entry in result["requests"]] == ["plain", "forced_tool"]
    assert "opaque-secret" not in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_forced_only_uses_remaining_slot_after_plain_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "_key", lambda: "private-test-key")
    prior_list = tmp_path / "model-list.json"
    prior_list.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "kind": "model_list",
                        "status": 200,
                        "chat_tool_models": ["mistral-medium-latest"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    prior_plain = tmp_path / "plain.json"
    prior_plain.write_text(
        json.dumps(
            {
                "model": "mistral-medium-latest",
                "target_availability": "eligible",
                "requests": [{"kind": "plain", "status": 429}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke, "PREVIOUS_SMOKE", prior_list)
    monkeypatch.setattr(smoke, "PREVIOUS_CONTINUATION", prior_plain)
    calls = 0

    def handler(req: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        assert req.method == "POST" and req.url.path == "/v1/chat/completions"
        payload = json.loads(req.content)
        assert payload["model"] == "mistral-medium-latest"
        assert payload["tool_choice"]["function"]["name"] == "get_truth_snapshot"
        return httpx2.Response(400, json={"error": {"message": "unsafe raw details"}})

    output = tmp_path / ".runtime" / "phase17b" / "forced.json"
    result = await smoke.run(
        output, transport=httpx2.MockTransport(handler), continuation=True, forced_only=True
    )
    assert calls == 1
    assert [entry["kind"] for entry in result["requests"]] == ["forced_tool"]
    assert result["previous_plain_status"] == 429
    assert "unsafe raw details" not in output.read_text(encoding="utf-8")
