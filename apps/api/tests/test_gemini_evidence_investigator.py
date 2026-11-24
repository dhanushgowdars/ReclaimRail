import logging
from importlib.metadata import version
from types import SimpleNamespace

import pytest
from google.genai import types as genai_types
from pydantic import ValidationError

import app.integrations.gemini.evidence_investigator as investigator_module
from app.core.config import Settings
from app.domain.investigation import InvestigationTurnAction, InvestigatorTurn
from app.integrations.gemini.evidence_investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderReason,
    GoogleGenAIEvidenceInvestigator,
    _classify_provider_error,
    _generate_content_turn,
    _provider_function_schema,
    build_gemini_generate_content_config,
)
from app.services.recovery_investigation_tools import public_tool_catalog


def read_only_request() -> dict[str, object]:
    tool = next(tool for tool in public_tool_catalog() if tool["name"] == "get_truth_snapshot")
    return {
        "objective": "Inspect only",
        "tools": (tool,),
    }


@pytest.mark.parametrize(
    ("status_code", "kind", "retryable"),
    [
        (401, EvidenceInvestigatorFailureKind.ACCESS_DENIED, False),
        (403, EvidenceInvestigatorFailureKind.ACCESS_DENIED, False),
        (429, EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED, False),
        (400, EvidenceInvestigatorFailureKind.PROVIDER_REJECTED, False),
        (500, EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER, True),
        (503, EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER, True),
    ],
)
def test_provider_errors_are_classified_without_exposing_payloads(
    status_code: int,
    kind: EvidenceInvestigatorFailureKind,
    retryable: bool,
) -> None:
    error = RuntimeError("private provider response")
    error.status_code = status_code  # type: ignore[attr-defined]

    classified = _classify_provider_error(error)

    assert classified.kind is kind
    assert classified.retryable is retryable
    assert classified.status_code == status_code
    assert "private provider response" not in str(classified)


def test_timeout_is_the_only_non_http_retryable_classification() -> None:
    classified = _classify_provider_error(TimeoutError("request contained secret data"))

    assert classified.kind is EvidenceInvestigatorFailureKind.TIMEOUT
    assert classified.retryable is True
    assert "secret" not in str(classified)


def test_locked_sdk_timeout_wrapper_is_classified_without_private_import() -> None:
    class APITimeoutError(Exception):
        pass

    classified = _classify_provider_error(APITimeoutError("private timeout payload"))

    assert classified.kind is EvidenceInvestigatorFailureKind.TIMEOUT
    assert classified.retryable is True
    assert "private timeout payload" not in str(classified)


def test_nested_transport_timeout_is_classified_without_exposing_cause() -> None:
    class ReadTimeout(Exception):
        pass

    wrapped = RuntimeError("private outer payload")
    wrapped.__cause__ = ReadTimeout("private transport payload")

    classified = _classify_provider_error(wrapped)

    assert classified.kind is EvidenceInvestigatorFailureKind.TIMEOUT
    assert classified.retryable is True
    assert "private" not in str(classified)


def test_enum_like_http_status_is_supported() -> None:
    error = RuntimeError("provider failure")
    error.code = SimpleNamespace(value=503)  # type: ignore[attr-defined]

    classified = _classify_provider_error(error)

    assert classified.kind is EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER
    assert classified.retryable is True


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("API key not valid: private-key-value", "credential_rejected"),
        ("Model gemini-private is not supported", "model_not_supported"),
        ("Thinking level minimal is unsupported", "thinking_level_rejected"),
        ("responseJsonSchema contains an invalid field", "response_schema_rejected"),
        ("structured output is unsupported", "structured_output_rejected"),
        ("maxOutputTokens is invalid", "generation_parameter_rejected"),
        ("Request contains an invalid argument", "invalid_argument"),
    ],
)
def test_provider_rejection_maps_to_fixed_reason_without_raw_message(
    message: str,
    reason: str,
) -> None:
    error = RuntimeError("raw details private-secret")
    error.status_code = 400  # type: ignore[attr-defined]
    error.status = "INVALID_ARGUMENT"  # type: ignore[attr-defined]
    error.message = message  # type: ignore[attr-defined]

    classified = _classify_provider_error(error)

    assert classified.kind is EvidenceInvestigatorFailureKind.PROVIDER_REJECTED
    assert classified.provider_status == "INVALID_ARGUMENT"
    assert classified.reason_code is EvidenceInvestigatorProviderReason(reason)
    assert message not in str(classified)
    assert "private-secret" not in str(classified)


def test_unknown_provider_status_is_not_copied_to_diagnostics() -> None:
    error = RuntimeError("raw payload")
    error.status_code = 400  # type: ignore[attr-defined]
    error.status = "PRIVATE_STATUS_SECRET"  # type: ignore[attr-defined]

    classified = _classify_provider_error(error)

    assert classified.provider_status is None
    assert classified.reason_code is EvidenceInvestigatorProviderReason.INVALID_ARGUMENT
    assert "PRIVATE_STATUS_SECRET" not in str(classified)


@pytest.mark.parametrize("thinking_level", ["low", "minimal"])
def test_locked_sdk_builds_generate_content_contract_offline(
    thinking_level: str,
) -> None:
    config = build_gemini_generate_content_config(
        read_only_request(),
        max_output_tokens=512,
        thinking_level=thinking_level,
        forced_tool_name="get_truth_snapshot",
    )
    wire = config.model_dump(by_alias=True, exclude_none=True)
    assert wire["maxOutputTokens"] == 512
    assert wire["seed"] == 0
    assert wire["thinkingConfig"] == {
        "includeThoughts": False,
        "thinkingLevel": thinking_level.upper(),
    }
    assert wire["automaticFunctionCalling"] == {
        "disable": True,
        "maximumRemoteCalls": 1,
    }
    assert wire["automaticContinuation"] is False
    function = wire["tools"][0]["functionDeclarations"][0]
    assert function == {
        "name": "get_truth_snapshot",
        "description": "Read current versioned payment truth",
        "parametersJsonSchema": {
            "type": "object",
            "properties": {"case_id": {"type": "string"}},
            "required": ["case_id"],
        },
    }
    assert wire["toolConfig"] == {
        "functionCallingConfig": {
            "allowedFunctionNames": ["get_truth_snapshot"],
            "mode": "ANY",
        },
    }
    serialized = repr(config)
    assert "offline-serialization-test-key" not in serialized
    assert "case-1" not in serialized


def test_production_contract_requires_one_of_evidence_complete_or_abstain_functions() -> None:
    config = build_gemini_generate_content_config(
        read_only_request(),
        max_output_tokens=512,
        thinking_level="minimal",
    )
    assert config.tools is not None
    functions = config.tools[0].function_declarations
    assert functions is not None
    assert [function.name for function in functions] == [
        "get_truth_snapshot",
        "complete_investigation",
        "abstain_investigation",
    ]
    terminal_contract = repr(
        [function.model_dump(by_alias=True, exclude_none=True) for function in functions[1:]],
    )
    for unsupported_schema_keyword in ("$defs", "$ref", "anyOf", "maxItems", "default"):
        assert unsupported_schema_keyword not in terminal_contract
    assert "additionalProperties" not in terminal_contract
    assert config.tool_config is not None
    assert config.tool_config.model_dump(by_alias=True, exclude_none=True) == {
        "functionCallingConfig": {
            "mode": "ANY",
            "allowedFunctionNames": [
                "get_truth_snapshot",
                "complete_investigation",
                "abstain_investigation",
            ],
        },
    }


def test_provider_schema_adapter_removes_pydantic_only_keywords_recursively() -> None:
    schema = {
        "type": "object",
        "title": "Ignored",
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "format": "uuid", "title": "Case Id"},
            "labels": {
                "type": "array",
                "items": {"type": "string", "title": "Label"},
                "maxItems": 3,
            },
        },
        "required": ["case_id"],
    }

    assert _provider_function_schema(schema) == {
        "type": "object",
        "properties": {
            "case_id": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["case_id"],
    }


def test_preflight_cannot_force_a_terminal_response_function() -> None:
    with pytest.raises(ValueError, match="not in the read-only tool catalog"):
        build_gemini_generate_content_config(
            read_only_request(),
            max_output_tokens=512,
            thinking_level="minimal",
            forced_tool_name="complete_investigation",
        )


@pytest.mark.parametrize(
    "tool_override",
    [
        {"read_only": False},
        {"name": "create_payment_link"},
        {"input_schema": "not-a-schema"},
    ],
)
def test_generate_content_contract_rejects_untrusted_tool_declarations(
    tool_override: dict[str, object],
) -> None:
    request = read_only_request()
    tool = dict(request["tools"][0])  # type: ignore[index]
    tool.update(tool_override)
    request["tools"] = (tool,)

    with pytest.raises(ValueError, match="read-only contract"):
        build_gemini_generate_content_config(
            request,
            max_output_tokens=512,
            thinking_level="minimal",
        )


def generate_content_response(
    *calls: tuple[str, dict[str, object]],
    text: str | None = None,
) -> genai_types.GenerateContentResponse:
    parts = [
        genai_types.Part.from_function_call(name=name, args=arguments) for name, arguments in calls
    ]
    if text is not None:
        parts.append(genai_types.Part.from_text(text=text))
    return genai_types.GenerateContentResponse(
        model_version="gemini-3.8-flash-001",
        candidates=[genai_types.Candidate(content=genai_types.Content(parts=parts))],
    )


def test_generate_content_maps_one_real_function_call_without_execution() -> None:
    response = generate_content_response(
        ("get_truth_snapshot", {"case_id": "case-1"}),
    )

    turn = _generate_content_turn(
        response,
        allowed_evidence_tool_names={"get_truth_snapshot"},
    )

    assert isinstance(turn, InvestigatorTurn)
    assert turn.action is InvestigationTurnAction.CALL_TOOL
    assert turn.tool_name == "get_truth_snapshot"
    assert turn.tool_arguments == {"case_id": "case-1"}


@pytest.mark.parametrize(
    ("function_name", "arguments", "expected_action"),
    [
        (
            "complete_investigation",
            {"summary": "Evidence supports a retryable failure.", "evidence_ids": ["ev-1"]},
            InvestigationTurnAction.COMPLETE,
        ),
        (
            "abstain_investigation",
            {"abstention_reason": "Evidence conflicts.", "evidence_ids": ["ev-1"]},
            InvestigationTurnAction.ABSTAIN,
        ),
    ],
)
def test_terminal_response_functions_map_to_strict_turns_without_execution(
    function_name: str,
    arguments: dict[str, object],
    expected_action: InvestigationTurnAction,
) -> None:
    response = generate_content_response((function_name, arguments))

    turn = _generate_content_turn(
        response,
        allowed_evidence_tool_names={"get_truth_snapshot"},
    )

    assert turn.action is expected_action
    assert turn.tool_name is None
    assert turn.tool_arguments is None


def test_terminal_response_function_arguments_still_enforce_application_limits() -> None:
    response = generate_content_response(
        ("complete_investigation", {"summary": "x" * 601, "evidence_ids": ["ev-1"]}),
    )

    with pytest.raises(ValidationError, match="summary"):
        _generate_content_turn(
            response,
            allowed_evidence_tool_names={"get_truth_snapshot"},
        )


def test_generate_content_rejects_multiple_or_unlisted_function_calls() -> None:
    response = generate_content_response(
        ("get_truth_snapshot", {"case_id": "case-1"}),
        ("get_provider_payment", {"case_id": "case-1"}),
    )

    with pytest.raises(ValueError, match="ambiguous"):
        _generate_content_turn(
            response,
            allowed_evidence_tool_names={"get_truth_snapshot", "get_provider_payment"},
        )

    response = generate_content_response(("create_payment_link", {"case_id": "case-1"}))
    with pytest.raises(ValueError, match="outside the declared allow-list"):
        _generate_content_turn(
            response,
            allowed_evidence_tool_names={"get_truth_snapshot"},
        )


def test_generate_content_rejects_free_text_instead_of_function_call() -> None:
    response = generate_content_response(text='{"action":"abstain"}')

    with pytest.raises(ValueError, match="ambiguous"):
        _generate_content_turn(
            response,
            allowed_evidence_tool_names={"get_truth_snapshot"},
        )


def test_sdk_http_retries_are_explicitly_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class StubClient:
        pass

    def client_factory(**kwargs: object) -> StubClient:
        captured.update(kwargs)
        return StubClient()

    monkeypatch.setattr(investigator_module.genai, "Client", client_factory)
    provider = GoogleGenAIEvidenceInvestigator(
        api_key="offline-test-key",
        model_name="gemini-3.6-flash",
        request_timeout_seconds=30,
    )

    provider._client()  # noqa: SLF001 - deterministic SDK-boundary assertion

    http_options = captured["http_options"]
    assert http_options.api_version == "v1beta"  # type: ignore[union-attr]
    assert http_options.timeout == 30_000  # type: ignore[union-attr]
    assert http_options.retry_options.attempts == 1  # type: ignore[union-attr]


def test_google_genai_sdk_is_locked_to_stabilized_transport_release() -> None:
    assert version("google-genai") == "2.34.0"


@pytest.mark.asyncio
async def test_adapter_discovers_model_then_uses_generate_content_without_executing_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_requests: list[str] = []
    generation_requests: list[dict[str, object]] = []

    class FakeModels:
        async def get(self, *, model: str) -> object:
            model_requests.append(model)
            return SimpleNamespace(
                name=f"models/{model}",
                version=f"{model}-001",
                input_token_limit=1_000_000,
                output_token_limit=8_192,
                thinking=True,
            )

        async def generate_content(self, **kwargs: object) -> genai_types.GenerateContentResponse:
            generation_requests.append(kwargs)
            response = generate_content_response(
                ("get_truth_snapshot", {"case_id": "case-1"}),
            )
            response.usage_metadata = genai_types.GenerateContentResponseUsageMetadata(
                prompt_token_count=50,
                candidates_token_count=7,
                total_token_count=57,
            )
            return response

    class FakeAsyncClient:
        def __init__(self) -> None:
            self.models = FakeModels()

        async def aclose(self) -> None:
            return None

    class FakeClient:
        def __init__(self) -> None:
            self.aio = FakeAsyncClient()

        def close(self) -> None:
            return None

    monkeypatch.setattr(investigator_module.genai, "Client", lambda **_: FakeClient())
    provider = GoogleGenAIEvidenceInvestigator(
        api_key="offline-test-key",
        model_name="gemini-3.6-flash",
        max_output_tokens=512,
        request_timeout_seconds=30,
        thinking_level="minimal",
        forced_tool_name="get_truth_snapshot",
    )

    access = await provider.discover_model_access()
    response = await provider.next_turn(read_only_request())

    assert model_requests == ["gemini-3.6-flash"]
    assert access.model_name == "gemini-3.6-flash"
    assert access.model_version == "gemini-3.6-flash-001"
    assert len(generation_requests) == 1
    assert generation_requests[0]["model"] == "gemini-3.6-flash"
    assert generation_requests[0]["contents"].startswith("Investigate this recovery case")
    config = generation_requests[0]["config"]
    assert isinstance(config, genai_types.GenerateContentConfig)
    assert config.automatic_continuation is False
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True
    assert config.automatic_function_calling.maximum_remote_calls == 1
    assert response.model_version == "gemini-3.6-flash-001"
    assert response.input_token_count == 50
    assert response.output_token_count == 7
    assert isinstance(response.turn, InvestigatorTurn)
    assert response.turn.action is InvestigationTurnAction.CALL_TOOL


def test_locked_sdk_thinking_levels_and_retry_range_are_validated() -> None:
    assert Settings(_env_file=None, gemini_thinking_level="minimal").gemini_thinking_level == (
        "minimal"
    )
    assert Settings(_env_file=None, gemini_thinking_level="low").gemini_thinking_level == "low"

    with pytest.raises(ValidationError, match="gemini_thinking_level"):
        Settings(_env_file=None, gemini_thinking_level="xhigh")
    with pytest.raises(ValidationError, match="retry maximum"):
        Settings(
            _env_file=None,
            recovery_investigator_retry_base_seconds=2,
            recovery_investigator_retry_max_seconds=1,
        )


class RetriableGeminiError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__("private provider body")
        self.status_code = status_code
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        self.response = SimpleNamespace(headers=headers)


@pytest.mark.asyncio
async def test_503_and_429_retry_twice_with_retry_after_and_backoff(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[str] = []
    sleeps: list[float] = []
    responses: list[object] = [
        RetriableGeminiError(503, "4"),
        RetriableGeminiError(429),
        generate_content_response(("get_truth_snapshot", {"case_id": "case-1"})),
    ]
    responses[-1].model_version = "gemini-primary-001"  # type: ignore[union-attr]

    class FakeModels:
        async def generate_content(self, **kwargs: object) -> object:
            requests.append(str(kwargs["model"]))
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

    class FakeAsyncClient:
        models = FakeModels()

        async def aclose(self) -> None:
            return None

    class FakeClient:
        aio = FakeAsyncClient()

        def close(self) -> None:
            return None

    monkeypatch.setattr(investigator_module.genai, "Client", lambda **_: FakeClient())
    provider = GoogleGenAIEvidenceInvestigator(
        api_key="offline-test-key",
        model_name="gemini-primary",
        fallback_model_name="gemini-fallback",
        forced_tool_name="get_truth_snapshot",
        sleep=lambda delay: _record_sleep(sleeps, delay),
    )

    with caplog.at_level(logging.INFO, logger=investigator_module.__name__):
        result = await provider.next_turn(read_only_request())

    assert requests == ["gemini-primary"] * 3
    assert sleeps == [4.0, 2.0]
    assert result.model_name == "gemini-primary-001"
    assert "served model=gemini-primary-001 requested_model=gemini-primary" in caplog.text
    assert "offline-test-key" not in caplog.text
    assert "Inspect only" not in caplog.text


async def _record_sleep(sleeps: list[float], delay: float) -> None:
    sleeps.append(delay)


@pytest.mark.asyncio
async def test_falls_back_after_primary_exhausts_two_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []
    sleeps: list[float] = []
    fallback_response = generate_content_response(("get_truth_snapshot", {"case_id": "case-1"}))
    fallback_response.model_version = "gemini-fallback-001"
    responses: list[object] = [
        RetriableGeminiError(503, "0"),
        RetriableGeminiError(503, "0"),
        RetriableGeminiError(503, "0"),
        fallback_response,
    ]

    class FakeModels:
        async def generate_content(self, **kwargs: object) -> object:
            requests.append(str(kwargs["model"]))
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

    class FakeAsyncClient:
        models = FakeModels()

        async def aclose(self) -> None:
            return None

    class FakeClient:
        aio = FakeAsyncClient()

        def close(self) -> None:
            return None

    monkeypatch.setattr(investigator_module.genai, "Client", lambda **_: FakeClient())
    provider = GoogleGenAIEvidenceInvestigator(
        api_key="offline-test-key",
        model_name="gemini-primary",
        fallback_model_name="gemini-fallback",
        forced_tool_name="get_truth_snapshot",
        sleep=lambda delay: _record_sleep(sleeps, delay),
    )

    result = await provider.next_turn(read_only_request())

    assert requests == ["gemini-primary"] * 3 + ["gemini-fallback"]
    assert sleeps == [0.0, 0.0]
    assert result.model_name == "gemini-fallback-001"


def test_gemini_primary_and_fallback_models_are_settings_backed() -> None:
    settings = Settings(
        _env_file=None,
        gemini_model_name="gemini-primary",
        gemini_fallback_model_name="gemini-fallback",
    )
    assert settings.gemini_model_name == "gemini-primary"
    assert settings.gemini_fallback_model_name == "gemini-fallback"
