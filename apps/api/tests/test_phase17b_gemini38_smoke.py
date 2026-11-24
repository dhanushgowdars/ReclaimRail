"""Mocked contract tests for the isolated Gemini 3.8 Flash smoke path."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.evaluation import phase17b_gemini38_smoke as smoke
from scripts import run_phase17b_gemini38_smoke as runner


@dataclass
class FakeUsage:
    total_input_tokens: int = 10
    total_output_tokens: int = 2
    total_thought_tokens: int = 3


class FakeModels:
    def __init__(self, response: object, expected_model: str = smoke.GEMINI_38_MODEL) -> None:
        self.response = response
        self.expected_model = expected_model
        self.calls = 0

    async def get(self, *, model: str) -> object:
        self.calls += 1
        assert model == self.expected_model
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class FakeInteractions:
    def __init__(self, responses: list[object], observed: list[dict[str, object]]) -> None:
        self.responses = responses
        self.observed = observed

    async def create(self, **kwargs: object) -> object:
        self.observed.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeClient:
    def __init__(
        self,
        model: object,
        responses: list[object],
        observed: list[dict[str, object]],
        expected_model: str = smoke.GEMINI_38_MODEL,
    ):
        self.aio = SimpleNamespace(
            models=FakeModels(model, expected_model),
            interactions=FakeInteractions(responses, observed),
            aclose=self.aclose,
        )

    async def aclose(self) -> None:
        return None

    def close(self) -> None:
        return None


def _interaction(
    *steps: object, text: str | None = None, model: str = smoke.GEMINI_38_MODEL
) -> object:
    return SimpleNamespace(
        model=model,
        steps=list(steps),
        output_text=text,
        usage=FakeUsage(),
        id="opaque-interaction-id",
    )


def test_key_presence_guard_uses_only_new_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("RECLAIMRAIL_GEMINI_API_KEY=historical\n", encoding="utf-8")
    monkeypatch.delenv(smoke.GEMINI_38_KEY_NAME, raising=False)
    with pytest.raises(smoke.Gemini38KeyMissingError, match=smoke.GEMINI_38_KEY_NAME):
        smoke.load_isolated_key(env_file)
    env_file.write_text(f"{smoke.GEMINI_38_KEY_NAME}=new-only\n", encoding="utf-8")
    assert smoke.load_isolated_key(env_file) == "new-only"


@pytest.mark.asyncio
async def test_model_availability_states_and_single_call() -> None:
    for returned, available in (("models/gemini-3.8-flash", True), ("models/other", False)):
        client = FakeClient(SimpleNamespace(name=returned), [], [])
        receipt = await smoke.run_smoke_request(
            "secret", "model_metadata", client_factory=lambda _, __, current=client: current
        )
        assert receipt.available is available
        assert client.aio.models.calls == 1


def test_request_serialization_uses_interactions_contract_and_real_read_only_tools() -> None:
    plain = smoke.plain_interaction_request()
    forced = smoke.forced_function_interaction_request()
    assert plain["model"] == forced["model"] == "gemini-3.8-flash"
    assert plain["automatic_continuation"] is False
    assert forced["automatic_continuation"] is False
    assert "response_format" not in plain and "response_format" not in forced
    assert forced["generation_config"]["tool_choice"] == {
        "allowed_tools": {"mode": "any", "tools": ["get_truth_snapshot"]}
    }
    tools = forced["tools"]
    assert len(tools) == 11
    assert {tool["name"] for tool in tools} == {
        item["name"] for item in smoke.public_tool_catalog()
    }
    assert all(
        "format" not in json.dumps(tool) and "title" not in json.dumps(tool) for tool in tools
    )


def test_hydrogen_request_uses_official_low_thinking_and_bounded_contract() -> None:
    plain = smoke.plain_interaction_request(smoke.GEMINI_4_HYDROGEN_MODEL)
    forced = smoke.forced_function_interaction_request(smoke.GEMINI_4_HYDROGEN_MODEL)
    for request in (plain, forced):
        assert request["model"] == "gemini-4-hydrogen"
        assert request["timeout"] == 120.0
        assert request["automatic_continuation"] is False
        assert request["generation_config"]["thinking_level"] == "low"
        assert request["generation_config"]["max_output_tokens"] == 256
        assert "response_format" not in request


def test_model_allowlist_and_current_model_list_sanitizer() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        smoke.resolve_smoke_model("gemini-4-neon")
    entry = SimpleNamespace(
        name="models/gemini-4-hydrogen",
        display_name="Gemini 4 Hydrogen",
        supported_actions=["generateContent", "countTokens"],
        supported_generation_methods=["legacy-should-not-be-read"],
        input_token_limit=1_048_576,
        output_token_limit=65_536,
        project_id="private-project",
    )
    assert smoke.sanitize_model_list_entry(entry) == {
        "model_id": "gemini-4-hydrogen",
        "display_name": "Gemini 4 Hydrogen",
        "supported_actions": ["countTokens", "generateContent"],
        "input_token_limit": 1_048_576,
        "output_token_limit": 65_536,
    }


@pytest.mark.asyncio
async def test_plain_and_forced_calls_disable_execution_and_validate_arguments() -> None:
    observed: list[dict[str, object]] = []
    call = SimpleNamespace(
        type="function_call",
        id="opaque-call-id",
        name="get_truth_snapshot",
        arguments={"case_id": smoke.GEMINI_38_CASE_ID},
    )
    responses = [_interaction(text="OK"), _interaction(call)]
    client = FakeClient(SimpleNamespace(name="models/gemini-3.8-flash"), responses, observed)

    def factory(_: str, __: float) -> FakeClient:
        return client

    plain = await smoke.run_smoke_request("secret", "plain", client_factory=factory)
    forced = await smoke.run_smoke_request("secret", "forced_function", client_factory=factory)
    assert plain.plain_exact_ok is True
    assert forced.function_name == "get_truth_snapshot" and forced.arguments_valid is True
    assert forced.automatic_function_execution_disabled is True
    assert len(observed) == 2
    assert all(item["automatic_continuation"] is False for item in observed)
    assert not any("function_result" in json.dumps(item) for item in observed)


@pytest.mark.asyncio
async def test_hydrogen_calls_use_target_model_and_120_second_client_timeout() -> None:
    observed: list[dict[str, object]] = []
    call = SimpleNamespace(
        type="function_call",
        id="opaque-call-id",
        name="get_truth_snapshot",
        arguments={"case_id": smoke.GEMINI_38_CASE_ID},
    )
    client = FakeClient(
        object(),
        [
            _interaction(text="OK", model=smoke.GEMINI_4_HYDROGEN_MODEL),
            _interaction(call, model=smoke.GEMINI_4_HYDROGEN_MODEL),
        ],
        observed,
        smoke.GEMINI_4_HYDROGEN_MODEL,
    )

    def factory(_: str, timeout: float) -> FakeClient:
        assert timeout == 120.0
        return client

    plain = await smoke.run_smoke_request(
        "secret",
        "plain",
        model_name=smoke.GEMINI_4_HYDROGEN_MODEL,
        client_factory=factory,
    )
    forced = await smoke.run_smoke_request(
        "secret",
        "forced_function",
        model_name=smoke.GEMINI_4_HYDROGEN_MODEL,
        client_factory=factory,
    )
    assert plain.requested_model == plain.returned_model == smoke.GEMINI_4_HYDROGEN_MODEL
    assert forced.requested_model == forced.returned_model == smoke.GEMINI_4_HYDROGEN_MODEL
    assert plain.plain_exact_ok is True
    assert forced.function_name == "get_truth_snapshot" and forced.arguments_valid is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "steps",
    [
        [],
        [SimpleNamespace(type="function_call", name="unknown", arguments={})],
        [
            SimpleNamespace(type="function_call", name="get_truth_snapshot", arguments={}),
            SimpleNamespace(type="function_call", name="get_truth_snapshot", arguments={}),
        ],
        [
            SimpleNamespace(
                type="function_call",
                name="get_truth_snapshot",
                arguments={"case_id": "not-a-uuid"},
            )
        ],
    ],
)
async def test_unknown_multiple_missing_and_invalid_function_calls_fail_closed(
    steps: list[object],
) -> None:
    client = FakeClient(object(), [_interaction(*steps)], [])
    receipt = await smoke.run_smoke_request(
        "secret", "forced_function", client_factory=lambda _, __: client
    )
    assert receipt.outcome == "failed_safe"
    assert receipt.arguments_valid is False
    assert receipt.function_name is None


class FakeProviderError(Exception):
    def __init__(self, status: int, *, headers: dict[str, str] | None = None) -> None:
        super().__init__("private raw provider body secret request-id")
        self.status_code = status
        self.response = SimpleNamespace(headers=headers or {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "category"),
    [
        (FakeProviderError(400), "invalid_request"),
        (FakeProviderError(403), "access_denied"),
        (FakeProviderError(404), "model_unavailable"),
        (FakeProviderError(429), "quota_exhausted"),
        (FakeProviderError(503), "provider_unavailable"),
        (TimeoutError("secret"), "timeout"),
    ],
)
async def test_provider_failure_mapping_is_closed(error: BaseException, category: str) -> None:
    client = FakeClient(object(), [error], [])
    receipt = await smoke.run_smoke_request("secret", "plain", client_factory=lambda _, __: client)
    assert receipt.provider_category == category
    assert "secret" not in json.dumps(smoke.sanitized_receipt(receipt))


@pytest.mark.asyncio
async def test_sanitized_quota_usage_and_exclusions() -> None:
    client = FakeClient(
        object(),
        [FakeProviderError(429, headers={"Retry-After": "7", "Authorization": "secret"})],
        [],
    )
    receipt = await smoke.run_smoke_request("secret", "plain", client_factory=lambda _, __: client)
    assert receipt.quota == {"retry_after_seconds": 7}
    saved = json.dumps(smoke.sanitized_receipt(receipt))
    for forbidden in ("Authorization", "private raw", "request-id", "opaque"):
        assert forbidden not in saved


@pytest.mark.asyncio
async def test_malformed_response_and_runner_stop_without_application_tool_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / ".runtime" / "phase17b"
    monkeypatch.setattr(runner, "API_ROOT", tmp_path)
    monkeypatch.setattr(runner, "load_isolated_key", lambda _: "secret")
    calls: list[str] = []

    async def fake_run(_: str, kind: Any, *, model_name: str) -> smoke.GeminiSmokeReceipt:
        calls.append(kind)
        return smoke.GeminiSmokeReceipt(
            request_kind=kind,
            outcome="failed_safe",
            http_status=404,
            provider_category="model_unavailable",
            provider_reason=None,
            latency_ms=1.0,
            requested_model=smoke.GEMINI_38_MODEL,
            returned_model=None,
            available=False,
        )

    monkeypatch.setattr(runner, "run_smoke_request", fake_run)
    results = await runner.run(output, label="test")
    assert calls == ["model_metadata"]
    assert len(results) == 1
    saved = next(output.glob("*.json")).read_text(encoding="utf-8")
    assert "prompt" not in saved and "objective" not in saved and "observation" not in saved


@pytest.mark.asyncio
async def test_hydrogen_runner_uses_two_slots_without_repeating_model_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / ".runtime" / "phase17b"
    monkeypatch.setattr(runner, "API_ROOT", tmp_path)
    monkeypatch.setattr(runner, "load_isolated_key", lambda _: "secret")
    calls: list[tuple[str, str]] = []

    async def fake_run(_: str, kind: Any, *, model_name: str) -> smoke.GeminiSmokeReceipt:
        calls.append((kind, model_name))
        return smoke.GeminiSmokeReceipt(
            request_kind=kind,
            outcome="succeeded",
            http_status=200,
            provider_category=None,
            provider_reason=None,
            latency_ms=1.0,
            requested_model=model_name,
            returned_model=model_name,
            plain_exact_ok=True if kind == "plain" else None,
            function_name="get_truth_snapshot" if kind == "forced_function" else None,
            arguments_valid=True if kind == "forced_function" else None,
        )

    monkeypatch.setattr(runner, "run_smoke_request", fake_run)
    results = await runner.run(
        output, model_name=smoke.GEMINI_4_HYDROGEN_MODEL, label="hydrogen-test"
    )
    assert calls == [
        ("plain", "gemini-4-hydrogen"),
        ("forced_function", "gemini-4-hydrogen"),
    ]
    assert len(results) == 2
    assert len(list(output.glob("gemini4-hydrogen-smoke-*.json"))) == 2


@pytest.mark.asyncio
async def test_hydrogen_refuses_metadata_request_before_client_construction() -> None:
    called = False

    def factory(_: str, __: float) -> FakeClient:
        nonlocal called
        called = True
        return FakeClient(object(), [], [])

    with pytest.raises(ValueError, match="does not authorize"):
        await smoke.run_smoke_request(
            "secret",
            "model_metadata",
            model_name=smoke.GEMINI_4_HYDROGEN_MODEL,
            client_factory=factory,
        )
    assert called is False


@pytest.mark.asyncio
async def test_timeout_enforces_one_transport_attempt() -> None:
    observed: list[dict[str, object]] = []

    class TimeoutInteractions(FakeInteractions):
        async def create(self, **kwargs: object) -> object:
            self.observed.append(kwargs)
            raise TimeoutError

    client = FakeClient(object(), [], observed)
    client.aio.interactions = TimeoutInteractions([], observed)
    receipt = await smoke.run_smoke_request("secret", "plain", client_factory=lambda _, __: client)
    assert receipt.provider_category == "timeout"
    assert receipt.transport_attempts == 1 and len(observed) == 1
