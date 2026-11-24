import json

import httpx2
import pytest

from app.domain.investigation import InvestigationTurnAction
from app.integrations.groq.evidence_investigator import GroqEvidenceInvestigator
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    EvidenceInvestigatorProviderReason,
    OrderedEvidenceInvestigator,
)
from app.services.recovery_investigation_tools import public_tool_catalog

CASE_ID = "93000000-0000-0000-0000-000000000001"


def request(observations: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "objective": "inspect",
        "case": {"id": CASE_ID},
        "tools": (public_tool_catalog()[0],),
        "observations": observations or [],
    }


def transport(status: int = 200, message: dict[str, object] | None = None) -> httpx2.MockTransport:
    body = {
        "model": "openai/gpt-oss-120b",
        "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        "choices": [
            {
                "message": message
                or {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_truth_snapshot",
                                "arguments": json.dumps({"case_id": CASE_ID}),
                            },
                        }
                    ],
                }
            }
        ],
    }
    return httpx2.MockTransport(lambda _: httpx2.Response(status, json=body))


def test_groq_missing_or_blank_key_fails_before_any_network_attempt() -> None:
    requests = 0

    def count_request(_: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(200, json={})

    for key in ("", "   "):
        with pytest.raises(EvidenceInvestigatorProviderError) as raised:
            GroqEvidenceInvestigator(
                api_key=key,
                model_name="openai/gpt-oss-120b",
                transport=httpx2.MockTransport(count_request),
            )
        assert raised.value.kind is EvidenceInvestigatorFailureKind.CONFIGURATION
        assert raised.value.reason_code is EvidenceInvestigatorProviderReason.KEY_MISSING
    assert requests == 0


@pytest.mark.asyncio
async def test_groq_maps_one_local_function_without_execution() -> None:
    provider = GroqEvidenceInvestigator(
        api_key="test-key", model_name="openai/gpt-oss-120b", transport=transport()
    )
    response = await provider.next_turn(request())
    assert response.turn.action is InvestigationTurnAction.CALL_TOOL
    assert response.turn.tool_name == "get_truth_snapshot"
    assert response.provider == "groq"


@pytest.mark.asyncio
async def test_groq_preserves_assistant_call_and_correlates_sequential_tool_result() -> None:
    payloads: list[dict[str, object]] = []
    messages = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "opaque_truth_1",
                    "function": {
                        "name": "get_truth_snapshot",
                        "arguments": json.dumps({"case_id": CASE_ID}),
                    },
                }
            ],
        },
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "opaque_terminal_2",
                    "function": {
                        "name": "complete_investigation",
                        "arguments": json.dumps(
                            {"summary": "safe", "evidence_ids": ["evidence-1"]}
                        ),
                    },
                }
            ],
        },
    ]

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        payloads.append(json.loads(http_request.content))
        return httpx2.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [{"message": messages.pop(0)}],
            },
        )

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    first = await provider.next_turn(request())
    assert first.turn.action is InvestigationTurnAction.CALL_TOOL
    second = await provider.next_turn(
        request(
            [
                {
                    "sequence": 1,
                    "tool": "get_truth_snapshot",
                    "outcome": "succeeded",
                    "evidence_ids": ("evidence-1",),
                    "payload": {"synthetic": True},
                }
            ]
        )
    )
    assert second.turn.action is InvestigationTurnAction.COMPLETE
    assert [message["role"] for message in payloads[1]["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assistant = payloads[1]["messages"][2]
    tool_result = payloads[1]["messages"][3]
    assert assistant["tool_calls"][0]["id"] == "opaque_truth_1"
    assert tool_result["tool_call_id"] == "opaque_truth_1"
    assert "name" not in tool_result


@pytest.mark.asyncio
async def test_groq_supports_multiple_sequential_read_only_tool_turns() -> None:
    tool_catalog = public_tool_catalog()
    calls: list[dict[str, object]] = []
    responses = [
        ("call_truth", "get_truth_snapshot"),
        ("call_webhooks", "get_verified_webhooks"),
    ]

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        calls.append(json.loads(http_request.content))
        if responses:
            call_id, name = responses.pop(0)
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "function": {"name": name, "arguments": json.dumps({"case_id": CASE_ID})},
                    }
                ],
            }
        else:
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "function": {
                            "name": "complete_investigation",
                            "arguments": json.dumps(
                                {"summary": "safe", "evidence_ids": ["truth-1", "webhook-1"]}
                            ),
                        },
                    }
                ],
            }
        return httpx2.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [{"message": message}],
            },
        )

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    await provider.next_turn({**request(), "tools": tool_catalog})
    await provider.next_turn(
        {
            **request(
                [
                    {
                        "sequence": 1,
                        "tool": "get_truth_snapshot",
                        "outcome": "succeeded",
                        "evidence_ids": ("truth-1",),
                        "payload": {"synthetic": True},
                    }
                ]
            ),
            "tools": tool_catalog,
        }
    )
    terminal = await provider.next_turn(
        {
            **request(
                [
                    {
                        "sequence": 1,
                        "tool": "get_truth_snapshot",
                        "outcome": "succeeded",
                        "evidence_ids": ("truth-1",),
                        "payload": {"synthetic": True},
                    },
                    {
                        "sequence": 2,
                        "tool": "get_verified_webhooks",
                        "outcome": "succeeded",
                        "evidence_ids": ("webhook-1",),
                        "payload": {"synthetic": True},
                    },
                ]
            ),
            "tools": tool_catalog,
        }
    )
    assert terminal.turn.action is InvestigationTurnAction.COMPLETE
    assert [message["role"] for message in calls[2]["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert calls[2]["messages"][3]["tool_call_id"] == "call_truth"
    assert calls[2]["messages"][5]["tool_call_id"] == "call_webhooks"
    assert "name" not in calls[2]["messages"][3]
    assert "name" not in calls[2]["messages"][5]


@pytest.mark.asyncio
async def test_frozen_turn_three_wire_shape_keeps_history_and_portable_schemas() -> None:
    payloads: list[dict[str, object]] = []
    replies = [
        ("call_first", "get_truth_snapshot"),
        ("call_second", "get_recovery_history"),
    ]

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        payloads.append(json.loads(http_request.content))
        if not replies:
            return httpx2.Response(422, text="not retained")
        call_id, name = replies.pop(0)
        return httpx2.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps({"case_id": CASE_ID}),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        )

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    base = {
        "benchmark": {"corpus": "frozen", "scenario_id": "p17b-04"},
        "objective": "inspect",
        "case": {"id": CASE_ID, "case_id": CASE_ID},
        "tools": public_tool_catalog(),
        "budgets_remaining": {"tool_calls": 8},
        "response_contract": "bounded",
    }
    first = await provider.next_turn({**base, "observations": []})
    first_observation = {
        "sequence": 1,
        "tool": first.turn.tool_name,
        "outcome": "succeeded",
        "evidence_ids": (),
        "payload": {},
    }
    second = await provider.next_turn({**base, "observations": [first_observation]})
    second_observation = {
        "sequence": 2,
        "tool": second.turn.tool_name,
        "outcome": "succeeded",
        "evidence_ids": (),
        "payload": {},
    }
    with pytest.raises(EvidenceInvestigatorProviderError) as raised:
        await provider.next_turn({**base, "observations": [first_observation, second_observation]})
    assert raised.value.kind is EvidenceInvestigatorFailureKind.PROVIDER_REJECTED
    assert raised.value.status_code == 422

    third = payloads[2]
    assert [message["role"] for message in third["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert third["tool_choice"] == "required"
    assert third["parallel_tool_calls"] is False
    assert [item["function"]["name"] for item in third["tools"]] == [
        item["function"]["name"] for item in payloads[0]["tools"]
    ]
    assert third["messages"][2]["tool_calls"][0]["id"] == third["messages"][3]["tool_call_id"]
    assert third["messages"][4]["tool_calls"][0]["id"] == third["messages"][5]["tool_call_id"]
    forbidden_schema_keys = {"title", "format", "additionalProperties", "$defs", "$ref"}

    def schema_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(schema_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(schema_keys(item) for item in value))
        return set()

    for definition in third["tools"]:
        assert not (schema_keys(definition["function"]["parameters"]) & forbidden_schema_keys)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observations",
    [
        [],
        [
            {
                "sequence": 1,
                "tool": "get_provider_payment",
                "outcome": "succeeded",
                "evidence_ids": ("evidence-1",),
                "payload": {},
            }
        ],
        [
            {
                "sequence": 1,
                "tool": "get_truth_snapshot",
                "outcome": "succeeded",
                "evidence_ids": ("evidence-1",),
                "payload": {},
            },
            {
                "sequence": 2,
                "tool": "get_truth_snapshot",
                "outcome": "succeeded",
                "evidence_ids": ("evidence-1",),
                "payload": {},
            },
        ],
    ],
)
async def test_groq_rejects_missing_mismatched_or_duplicate_tool_results_before_network(
    observations: list[dict[str, object]],
) -> None:
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "opaque_truth_1",
                                    "function": {
                                        "name": "get_truth_snapshot",
                                        "arguments": json.dumps({"case_id": CASE_ID}),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        )

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    await provider.next_turn(request())
    with pytest.raises(EvidenceInvestigatorProviderError) as raised:
        await provider.next_turn(request(observations))
    assert raised.value.kind is EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args,action",
    [
        (
            "complete_investigation",
            {"summary": "safe", "evidence_ids": ["e1"]},
            InvestigationTurnAction.COMPLETE,
        ),
        (
            "abstain_investigation",
            {"abstention_reason": "uncertain"},
            InvestigationTurnAction.ABSTAIN,
        ),
    ],
)
async def test_groq_maps_terminal_functions(
    name: str, args: dict[str, object], action: InvestigationTurnAction
) -> None:
    message = {
        "content": None,
        "tool_calls": [
            {"id": "call_terminal", "function": {"name": name, "arguments": json.dumps(args)}}
        ],
    }
    response = await GroqEvidenceInvestigator(
        api_key="test-key", model_name="openai/gpt-oss-120b", transport=transport(message=message)
    ).next_turn(request())
    assert response.turn.action is action


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {"content": "free text", "tool_calls": []},
        {
            "content": None,
            "tool_calls": [
                {"id": "call_unknown", "function": {"name": "unknown", "arguments": "{}"}}
            ],
        },
        {
            "content": None,
            "tool_calls": [
                {"id": "call_one", "function": {"name": "get_truth_snapshot", "arguments": "{}"}},
                {"id": "call_two", "function": {"name": "get_truth_snapshot", "arguments": "{}"}},
            ],
        },
    ],
)
async def test_groq_rejects_unsafe_or_ambiguous_output(message: dict[str, object]) -> None:
    provider = GroqEvidenceInvestigator(
        api_key="test-key", model_name="openai/gpt-oss-120b", transport=transport(message=message)
    )
    with pytest.raises(Exception) as raised:
        await provider.next_turn(request())
    assert "test-key" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,kind",
    [
        (400, EvidenceInvestigatorFailureKind.PROVIDER_REJECTED),
        (401, EvidenceInvestigatorFailureKind.ACCESS_DENIED),
        (403, EvidenceInvestigatorFailureKind.ACCESS_DENIED),
        (429, EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED),
        (503, EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER),
    ],
)
async def test_groq_http_failures_are_sanitized(
    status: int, kind: EvidenceInvestigatorFailureKind
) -> None:
    provider = GroqEvidenceInvestigator(
        api_key="private-key", model_name="openai/gpt-oss-120b", transport=transport(status=status)
    )
    with pytest.raises(Exception) as raised:
        await provider.next_turn(request())
    assert raised.value.kind is kind
    assert "private-key" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,category",
    [
        ({"x-ratelimit-remaining-requests": "0"}, "request"),
        ({"x-ratelimit-remaining-tokens": "0"}, "token"),
        (
            {
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-remaining-tokens": "0",
            },
            "request_and_token",
        ),
        ({"x-untrusted-rate-limit": "0"}, "unknown"),
    ],
)
async def test_groq_429_diagnostics_are_allowlisted(headers: dict[str, str], category: str) -> None:
    safe_headers = {
        **headers,
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-reset-requests": "2s",
        "retry-after": "3",
        "authorization": "Bearer private-key",
        "x-arbitrary-private-header": "private-body",
    }
    provider = GroqEvidenceInvestigator(
        api_key="private-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(429, headers=safe_headers, text="private-body")
        ),
    )
    with pytest.raises(EvidenceInvestigatorProviderError) as raised:
        await provider.next_turn(request())
    error = raised.value
    assert error.kind is EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED
    assert error.rate_limit_metadata is not None
    diagnostic = error.rate_limit_metadata.as_dict()
    assert diagnostic["category"] == category
    assert diagnostic["request_limit"] == 100
    assert diagnostic["request_reset_seconds"] == 2.0
    assert diagnostic["retry_after_seconds"] == 3.0
    assert "private-key" not in str(diagnostic)
    assert "private-body" not in str(diagnostic)


@pytest.mark.asyncio
async def test_groq_400_discards_body_and_untrusted_headers() -> None:
    provider = GroqEvidenceInvestigator(
        api_key="private-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                400,
                headers={"x-untrusted": "private-header"},
                text="private provider error body",
            )
        ),
    )
    with pytest.raises(EvidenceInvestigatorProviderError) as raised:
        await provider.next_turn(request())
    assert raised.value.kind is EvidenceInvestigatorFailureKind.PROVIDER_REJECTED
    assert raised.value.rate_limit_metadata is None
    assert "private" not in str(raised.value)


@pytest.mark.asyncio
async def test_chain_fails_over_once_only_for_eligible_failure() -> None:
    class Primary:
        provider_name = "primary"
        calls = 0

        async def next_turn(self, value: dict[str, object]) -> object:
            self.calls += 1
            raise EvidenceInvestigatorProviderError(
                "safe",
                kind=EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
                retryable=False,
                status_code=503,
            )

    class Secondary:
        provider_name = "secondary"
        calls = 0

        async def next_turn(self, value: dict[str, object]) -> object:
            self.calls += 1
            return "selected"

    primary, secondary = Primary(), Secondary()
    chain = OrderedEvidenceInvestigator((primary, secondary))  # type: ignore[arg-type]
    assert await chain.next_turn({}) == "selected"
    assert (primary.calls, secondary.calls) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [EvidenceInvestigatorFailureKind.TIMEOUT, EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER],
)
async def test_chain_fails_over_for_timeout_and_connection_classifications(
    kind: EvidenceInvestigatorFailureKind,
) -> None:
    class Failing:
        provider_name = "first"
        calls = 0

        async def next_turn(self, value: dict[str, object]) -> object:
            self.calls += 1
            raise EvidenceInvestigatorProviderError("sanitized", kind=kind, retryable=False)

    class Selected:
        provider_name = "second"
        calls = 0

        async def next_turn(self, value: dict[str, object]) -> object:
            self.calls += 1
            return "selected"

    first, second = Failing(), Selected()
    assert await OrderedEvidenceInvestigator((first, second)).next_turn({}) == "selected"  # type: ignore[arg-type]
    assert (first.calls, second.calls) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
        EvidenceInvestigatorFailureKind.ACCESS_DENIED,
    ],
)
async def test_chain_never_fails_over_for_rejected_or_access_denied(
    kind: EvidenceInvestigatorFailureKind,
) -> None:
    class Failing:
        provider_name = "first"

        async def next_turn(self, value: dict[str, object]) -> object:
            raise EvidenceInvestigatorProviderError(
                "sanitized", kind=kind, retryable=False, status_code=400
            )

    class MustNotRun:
        provider_name = "second"
        calls = 0

        async def next_turn(self, value: dict[str, object]) -> object:
            self.calls += 1
            return "unsafe"

    second = MustNotRun()
    with pytest.raises(EvidenceInvestigatorProviderError):
        await OrderedEvidenceInvestigator((Failing(), second)).next_turn({})  # type: ignore[arg-type]
    assert second.calls == 0


def test_chain_rejects_more_than_two_providers() -> None:
    with pytest.raises(ValueError, match="one or two"):
        OrderedEvidenceInvestigator((object(), object(), object()))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_groq_400_preserves_provider_fields_for_sanitized_receipt() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            headers={"x-request-id": "req_123", "authorization": "Bearer secret"},
            json={
                "error": {
                    "code": "tool_use_failed",
                    "type": "invalid_request_error",
                    "message": "Tool failed: bearer secret",
                    "failed_generation": "<tool_call>bad</tool_call>",
                }
            },
        )

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(EvidenceInvestigatorProviderError):
        await provider.next_turn(request())
    from scripts.run_phase17b_groq_benchmark import _safe_diagnostic_details

    receipt = _safe_diagnostic_details(provider.last_diagnostic_details)
    assert receipt["http_status"] == 400
    assert receipt["provider_error_code"] == "tool_use_failed"
    assert receipt["provider_error_type"] == "invalid_request_error"
    assert receipt["provider_error_message"] == "Tool failed: [REDACTED_BEARER]"
    assert receipt["failed_generation"] == "<tool_call>bad</tool_call>"
    assert receipt["x_request_id"] == "req_123"
    assert len(receipt["tool_declarations_sha256"]) == 64
    assert receipt["tool_choice"] == "required"
    assert receipt["parallel_tool_calls"] is False
    assert receipt["message_structure"][0]["role"] == "system"
    assert "authorization" not in json.dumps(receipt).lower()


@pytest.mark.asyncio
async def test_tool_failure_retry_reuses_identical_tool_result_messages() -> None:
    payloads: list[dict[str, object]] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        payloads.append(json.loads(http_request.content))
        if len(payloads) == 2:
            return httpx2.Response(
                400, json={"error": {"code": "tool_use_failed", "message": "bad JSON"}}
            )
        name = "get_truth_snapshot" if len(payloads) == 1 else "complete_investigation"
        args = (
            {"case_id": CASE_ID}
            if len(payloads) == 1
            else {"summary": "safe", "evidence_ids": ["e1"]}
        )
        return httpx2.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1" if len(payloads) == 1 else "call_2",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        }
                    }
                ],
            },
        )

    provider = GroqEvidenceInvestigator(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        transport=httpx2.MockTransport(handler),
    )
    await provider.next_turn(request())
    observation = [
        {
            "sequence": 1,
            "tool": "get_truth_snapshot",
            "outcome": "succeeded",
            "evidence_ids": ("e1",),
            "payload": {"synthetic": True},
        }
    ]
    with pytest.raises(EvidenceInvestigatorProviderError):
        await provider.next_turn(request(observation))
    await provider.next_turn(request(observation))
    assert payloads[1] == payloads[2]
