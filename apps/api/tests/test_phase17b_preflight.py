import json
from collections.abc import Iterator

import pytest

import app.evaluation.phase17b_preflight as preflight
from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.evaluation.phase17b_preflight import (
    LIVE_PREFLIGHT_ACKNOWLEDGEMENT,
    PREFLIGHT_CASE_ID,
    PREFLIGHT_MAX_OUTPUT_TOKENS,
    PREFLIGHT_REQUEST_BUDGET,
    PREFLIGHT_REQUEST_TIMEOUT_SECONDS,
    PREFLIGHT_TOOL_NAME,
    Phase17BPreflightCandidate,
    build_preflight_request,
    run_phase17b_preflight,
    sanitized_preflight_report_json,
    validate_preflight_authorization,
)
from app.integrations.gemini.evidence_investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    EvidenceInvestigatorProviderReason,
    GeminiModelAccessEvidence,
)


def deterministic_clock() -> Iterator[int]:
    yield 1_000_000_000
    yield 1_012_345_000


class RecordingProvider:
    def __init__(
        self,
        response: InvestigatorProviderResponse,
        *,
        model_access: GeminiModelAccessEvidence | None = None,
    ) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []
        self.discovery_calls = 0
        self.model_access = model_access or valid_model_access()

    async def discover_model_access(self) -> GeminiModelAccessEvidence:
        self.discovery_calls += 1
        return self.model_access

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        self.requests.append(request)
        return self.response


def valid_model_access(
    *,
    model: str = "gemini-3.8-flash",
    version: str | None = "gemini-3.8-flash-001",
    output_token_limit: int | None = 8192,
    thinking_supported: bool | None = True,
) -> GeminiModelAccessEvidence:
    return GeminiModelAccessEvidence(
        model_name=model,
        model_version=version,
        input_token_limit=1_000_000,
        output_token_limit=output_token_limit,
        thinking_supported=thinking_supported,
    )


def valid_response(
    *,
    model: str = "gemini-3.8-flash",
    model_version: str | None = "gemini-3.8-flash-001",
    turn: object | None = None,
    input_tokens: int | None = 42,
    output_tokens: int | None = 11,
) -> InvestigatorProviderResponse:
    return InvestigatorProviderResponse(
        turn=turn
        or InvestigatorTurn(
            action=InvestigationTurnAction.CALL_TOOL,
            tool_name=PREFLIGHT_TOOL_NAME,
            tool_arguments={"case_id": PREFLIGHT_CASE_ID},
        ),
        model_name=model,
        model_version=model_version,
        input_token_count=input_tokens,
        output_token_count=output_tokens,
    )


@pytest.mark.parametrize(
    ("model", "thinking_level"),
    [
        ("gemini-3.8-flash", "low"),
        ("gemini-3.6-flash", "minimal"),
    ],
)
def test_only_locked_model_and_thinking_pairs_are_authorized(
    model: str,
    thinking_level: str,
) -> None:
    candidate = validate_preflight_authorization(
        acknowledgement=LIVE_PREFLIGHT_ACKNOWLEDGEMENT,
        request_budget=PREFLIGHT_REQUEST_BUDGET,
        model=model,
        thinking_level=thinking_level,
    )

    assert candidate == Phase17BPreflightCandidate(model, thinking_level)


def test_preflight_provider_budget_is_small_deterministic_and_isolated() -> None:
    assert PREFLIGHT_MAX_OUTPUT_TOKENS == 512
    assert PREFLIGHT_REQUEST_TIMEOUT_SECONDS == 30.0
    assert PREFLIGHT_REQUEST_BUDGET == 2


@pytest.mark.parametrize(
    "catalog",
    [
        (),
        ({"name": PREFLIGHT_TOOL_NAME, "read_only": False},),
    ],
)
def test_preflight_refuses_missing_or_mutating_tool(
    monkeypatch: pytest.MonkeyPatch,
    catalog: tuple[dict[str, object], ...],
) -> None:
    monkeypatch.setattr(preflight, "public_tool_catalog", lambda: catalog)

    with pytest.raises(RuntimeError, match="must exist and remain read-only"):
        build_preflight_request()


@pytest.mark.parametrize(
    ("acknowledgement", "budget", "model", "thinking"),
    [
        ("wrong", 2, "gemini-3.8-flash", "low"),
        (LIVE_PREFLIGHT_ACKNOWLEDGEMENT, 1, "gemini-3.8-flash", "low"),
        (LIVE_PREFLIGHT_ACKNOWLEDGEMENT, 2, "gemini-3.7-flash", "low"),
        (LIVE_PREFLIGHT_ACKNOWLEDGEMENT, 2, "gemini-3.8-flash", "minimal"),
        (LIVE_PREFLIGHT_ACKNOWLEDGEMENT, 2, "gemini-4-hydrogen", "low"),
    ],
)
def test_preflight_refuses_unapproved_route_or_budget(
    acknowledgement: str,
    budget: int,
    model: str,
    thinking: str,
) -> None:
    with pytest.raises(ValueError):
        validate_preflight_authorization(
            acknowledgement=acknowledgement,
            request_budget=budget,
            model=model,
            thinking_level=thinking,
        )


@pytest.mark.asyncio
async def test_preflight_makes_one_synthetic_request_and_executes_no_tool() -> None:
    provider = RecordingProvider(valid_response())
    clock = deterministic_clock()

    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )

    assert report.status == "passed"
    assert report.request_count == 2
    assert report.api_route == "generate_content"
    assert report.model_discovery_valid is True
    assert report.discovered_model_version == "gemini-3.8-flash-001"
    assert report.latency_ms == 12.345
    assert report.schema_valid is True
    assert report.tool_contract_valid is True
    assert report.provider_model_version == "gemini-3.8-flash-001"
    assert len(provider.requests) == 1
    assert provider.discovery_calls == 1
    assert provider.requests[0] == build_preflight_request()
    assert provider.requests[0]["preflight"] == {
        "id": "reclaimrail-phase17b-model-access-v1",
        "evidence_mode": "controlled_synthetic",
        "purpose": "verify access, structured output, and read-only tool selection",
    }
    tools = provider.requests[0]["tools"]
    assert isinstance(tools, tuple)
    assert len(tools) == 1
    assert tools[0]["name"] == PREFLIGHT_TOOL_NAME
    assert tools[0]["read_only"] is True


@pytest.mark.asyncio
async def test_model_discovery_failure_stops_before_generation() -> None:
    class DiscoveryFailureProvider:
        generation_calls = 0

        async def discover_model_access(self) -> GeminiModelAccessEvidence:
            raise EvidenceInvestigatorProviderError(
                "sanitized discovery failure",
                kind=EvidenceInvestigatorFailureKind.ACCESS_DENIED,
                retryable=False,
                status_code=403,
            )

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.generation_calls += 1
            return valid_response()

    provider = DiscoveryFailureProvider()
    clock = deterministic_clock()

    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )

    assert report.status == "failed_safe"
    assert report.request_count == 1
    assert report.model_discovery_valid is False
    assert report.terminal_reason == "model_discovery_access_denied"
    assert provider.generation_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_access",
    [
        valid_model_access(model="private-wrong-model"),
        valid_model_access(output_token_limit=128),
        valid_model_access(thinking_supported=False),
    ],
)
async def test_model_discovery_contract_mismatch_stops_before_generation(
    model_access: GeminiModelAccessEvidence,
) -> None:
    provider = RecordingProvider(valid_response(), model_access=model_access)
    clock = deterministic_clock()

    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )

    assert report.status == "failed_safe"
    assert report.request_count == 1
    assert report.model_discovery_valid is False
    assert report.terminal_reason == "model_discovery_contract_mismatch"
    assert provider.requests == []


@pytest.mark.asyncio
async def test_quota_failure_is_sanitized_and_not_retried() -> None:
    class QuotaProvider:
        calls = 0

        async def discover_model_access(self) -> GeminiModelAccessEvidence:
            return valid_model_access()

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            raise EvidenceInvestigatorProviderError(
                "private provider response containing key-secret",
                kind=EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED,
                retryable=False,
                status_code=429,
            )

    provider = QuotaProvider()
    clock = deterministic_clock()
    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )
    serialized = sanitized_preflight_report_json(report)

    assert provider.calls == 1
    assert report.status == "failed_safe"
    assert report.failure_kind == "quota_exhausted"
    assert report.provider_status_code == 429
    assert report.provider_status is None
    assert report.provider_reason_code is None
    assert "private provider response" not in serialized
    assert "key-secret" not in serialized


@pytest.mark.asyncio
async def test_retryable_provider_failure_is_still_called_only_once() -> None:
    class TransientProvider:
        calls = 0

        async def discover_model_access(self) -> GeminiModelAccessEvidence:
            return valid_model_access()

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            raise EvidenceInvestigatorProviderError(
                "private transient response",
                kind=EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
                retryable=True,
                status_code=503,
            )

    provider = TransientProvider()
    clock = deterministic_clock()

    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )

    assert provider.calls == 1
    assert report.status == "failed_safe"
    assert report.failure_kind == "transient_provider"
    assert report.provider_status_code == 503
    assert report.provider_status is None
    assert report.provider_reason_code is None


@pytest.mark.asyncio
async def test_rejected_request_exposes_only_fixed_safe_reason_codes() -> None:
    class RejectedProvider:
        async def discover_model_access(self) -> GeminiModelAccessEvidence:
            return valid_model_access(
                model="gemini-3.6-flash",
                version="gemini-3.6-flash-001",
            )

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            raise EvidenceInvestigatorProviderError(
                "sanitized provider rejection",
                kind=EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
                retryable=False,
                status_code=400,
                provider_status="INVALID_ARGUMENT",
                reason_code=EvidenceInvestigatorProviderReason.RESPONSE_SCHEMA_REJECTED,
            )

    clock = deterministic_clock()
    report = await run_phase17b_preflight(
        RejectedProvider(),
        Phase17BPreflightCandidate("gemini-3.6-flash", "minimal"),
        monotonic_ns=lambda: next(clock),
    )
    serialized = sanitized_preflight_report_json(report)

    assert report.provider_status == "INVALID_ARGUMENT"
    assert report.provider_reason_code == "response_schema_rejected"
    assert "sanitized provider rejection" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (valid_response(model_version=None), "provider_model_version_missing_or_invalid"),
        (
            valid_response(model_version="private provider payload\napi_key=secret"),
            "provider_model_version_missing_or_invalid",
        ),
        (valid_response(input_tokens=None), "usage_metadata_incomplete"),
        (valid_response(output_tokens=0), "usage_metadata_incomplete"),
        (
            valid_response(
                turn=InvestigatorTurn(
                    action=InvestigationTurnAction.CALL_TOOL,
                    tool_name="get_provider_payment",
                    tool_arguments={"case_id": PREFLIGHT_CASE_ID},
                ),
            ),
            "tool_contract_mismatch",
        ),
        (valid_response(turn={"action": "complete"}), "malformed_model_output"),
    ],
)
async def test_incomplete_or_wrong_provider_response_fails_safe(
    response: InvestigatorProviderResponse,
    reason: str,
) -> None:
    provider = RecordingProvider(response)
    clock = deterministic_clock()

    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )

    assert report.status == "failed_safe"
    assert report.terminal_reason == reason
    assert len(provider.requests) == 1
    serialized = sanitized_preflight_report_json(report)
    assert "api_key=secret" not in serialized


@pytest.mark.asyncio
async def test_mismatched_adapter_model_is_not_copied_to_report() -> None:
    provider = RecordingProvider(valid_response(model="private-secret-model-value"))
    clock = deterministic_clock()

    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )
    serialized = sanitized_preflight_report_json(report)

    assert report.status == "failed_safe"
    assert report.terminal_reason == "adapter_model_mismatch"
    assert report.adapter_model_name is None
    assert "private-secret-model-value" not in serialized


@pytest.mark.asyncio
async def test_sanitized_report_contains_no_prompt_response_or_credential_fields() -> None:
    provider = RecordingProvider(valid_response())
    clock = deterministic_clock()
    report = await run_phase17b_preflight(
        provider,
        Phase17BPreflightCandidate("gemini-3.8-flash", "low"),
        monotonic_ns=lambda: next(clock),
    )
    serialized = sanitized_preflight_report_json(report)
    payload = json.loads(serialized)

    assert set(payload) == {
        "adapter_model_name",
        "api_route",
        "discovered_model_version",
        "evidence_mode",
        "failure_kind",
        "input_token_count",
        "latency_ms",
        "model_discovery_valid",
        "output_token_count",
        "provider_model_version",
        "provider_reason_code",
        "provider_status",
        "provider_status_code",
        "request_count",
        "requested_model",
        "schema_valid",
        "status",
        "terminal_reason",
        "thinking_level",
        "tool_contract_valid",
    }
    for forbidden in ("api_key", "prompt", "response", "objective", PREFLIGHT_CASE_ID):
        assert forbidden not in serialized.lower()
