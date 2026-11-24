"""Mocked safety and linkage tests for the controlled Hydrogen canary."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

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
from app.evaluation.phase17b_gemini_hydrogen_canary import (
    CANARY_CASE_ID,
    GEMINI_35_FLASH_MODEL,
    MAX_REQUEST_STARTS,
    HydrogenCanaryProvider,
    ValidationFailureReason,
    build_canary_report,
    run_controlled_hydrogen_canary,
    sanitized_report_json,
)
from app.integrations.investigator import EvidenceInvestigatorProviderError
from app.services.recovery_investigation_tools import public_tool_catalog
from scripts import run_phase17b_gemini_hydrogen_canary as runner


class FakeInteractions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.interactions = FakeInteractions(responses)
        self.aio = SimpleNamespace(interactions=self.interactions, aclose=self.aclose)
        self.closed = False

    async def aclose(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _usage() -> object:
    return SimpleNamespace(
        total_input_tokens=100,
        total_output_tokens=20,
        total_thought_tokens=5,
    )


def _call(name: str, arguments: object, call_id: str) -> object:
    return SimpleNamespace(type="function_call", name=name, arguments=arguments, id=call_id)


def _response(interaction_id: str, *calls: object) -> object:
    return SimpleNamespace(
        id=interaction_id, model="gemini-4-hydrogen", steps=list(calls), usage=_usage()
    )


def _provider(responses: list[object]) -> tuple[HydrogenCanaryProvider, FakeClient]:
    client = FakeClient(responses)
    provider = HydrogenCanaryProvider(
        api_key="offline-test-key",
        client_factory=lambda _key, _timeout: client,
    )
    return provider, client


def _passing_responses(terminal: str = "abstain_investigation") -> list[object]:
    terminal_arguments: dict[str, object]
    if terminal == "abstain_investigation":
        terminal_arguments = {
            "abstention_reason": "The controlled evidence is intentionally insufficient.",
            "evidence_ids": ["canary-evidence-1", "canary-evidence-2"],
            "hypotheses": [],
        }
    else:
        terminal_arguments = {
            "summary": "The controlled evidence supports a bounded conclusion.",
            "evidence_ids": ["canary-evidence-1", "canary-evidence-2"],
            "hypotheses": [],
        }
    return [
        _response(
            "interaction-one", _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "call-one")
        ),
        _response(
            "interaction-two",
            _call("get_verified_webhooks", {"case_id": CANARY_CASE_ID}, "call-two"),
        ),
        _response("interaction-three", _call(terminal, terminal_arguments, "call-three")),
    ]


@pytest.mark.asyncio
async def test_natural_tool_selection_linkage_frozen_lookup_and_safe_abstention() -> None:
    provider, client = _provider(_passing_responses())
    try:
        report = await run_controlled_hydrogen_canary(provider)
    finally:
        await provider.aclose()

    assert report.final_status == "passed"
    assert report.requests_started == report.responses_received == 3
    assert report.function_linkage_passed is True
    assert report.terminal_action == "abstain"
    assert report.citations_valid is report.truth_compatible is report.failed_safe is True
    assert report.tool_execution_count == 0
    assert [turn.public_name for turn in report.turns] == [
        "get_truth_snapshot",
        "get_verified_webhooks",
        "abstain_investigation",
    ]

    first, second, third = client.interactions.requests
    assert "previous_interaction_id" not in first
    assert "tool_choice" not in first["generation_config"]
    assert first["automatic_continuation"] is False
    assert len(first["tools"]) == 13
    assert second["previous_interaction_id"] == "interaction-one"
    assert third["previous_interaction_id"] == "interaction-two"
    assert second["input"][0]["call_id"] == "call-one"
    assert third["input"][0]["call_id"] == "call-two"
    second_result = json.loads(second["input"][0]["result"][0]["text"])
    third_result = json.loads(third["input"][0]["result"][0]["text"])
    assert second_result["evidence_ids"] == ["canary-evidence-1"]
    assert third_result["evidence_ids"] == ["canary-evidence-2"]
    assert client.closed is True


class ScriptedProvider:
    provider_name = "mock"

    def __init__(self, turns: list[InvestigatorTurn]) -> None:
        self.turns = turns
        self.requests: list[dict[str, object]] = []

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        self.requests.append(request)
        return InvestigatorProviderResponse(
            turn=self.turns.pop(0),
            model_name="mock",
            input_token_count=1,
            output_token_count=1,
        )


@pytest.mark.asyncio
async def test_authoritative_engine_accepts_safe_cited_completion() -> None:
    scenario = FrozenInvestigationScenario(
        scenario_id="p17b-19",
        objective="Inspect controlled evidence.",
        case_payload={"case_id": CANARY_CASE_ID},
        required_tools=("get_truth_snapshot",),
        expected_terminal="complete",
        expected_evidence_ids=("evidence-one",),
        tool_observations={
            "get_truth_snapshot": FrozenToolObservation(
                outcome="succeeded",
                evidence_ids=("evidence-one",),
                payload={"mode": "controlled_synthetic"},
            )
        },
    )
    provider = ScriptedProvider(
        [
            InvestigatorTurn(
                action=InvestigationTurnAction.CALL_TOOL,
                tool_name="get_truth_snapshot",
                tool_arguments={"case_id": CANARY_CASE_ID},
            ),
            InvestigatorTurn(
                action=InvestigationTurnAction.COMPLETE,
                summary="Controlled evidence supports the conclusion.",
                evidence_ids=("evidence-one",),
            ),
        ]
    )
    result = await run_frozen_scenario(provider, scenario, max_requests=5)
    assert result.terminal_action == "complete"
    assert result.citations_valid is result.truth_compatible is result.failed_safe is True
    assert provider.requests[1]["observations"][0]["evidence_ids"] == ("evidence-one",)


@pytest.mark.asyncio
async def test_invalid_citation_and_failed_safe_terminal_are_rejected() -> None:
    responses = _passing_responses()
    responses[-1] = _response(
        "interaction-three",
        _call(
            "abstain_investigation",
            {"abstention_reason": "Insufficient.", "evidence_ids": ["unseen-evidence"]},
            "call-three",
        ),
    )
    provider, _ = _provider(responses)
    report = await run_controlled_hydrogen_canary(provider)
    assert report.final_status == "invalid_citations"
    assert report.citations_valid is False

    unsafe_result = BenchmarkScenarioResult(
        scenario_id="p17b-18",
        selected_tools=("get_truth_snapshot",),
        terminal_action="abstain",
        request_count=2,
        truth_compatible=True,
        required_tools_selected=True,
        citations_valid=True,
        abstention_correct=True,
        provider_failed=False,
        malformed_output=False,
        failed_safe=False,
        terminal_reason="terminal_turn",
    )
    unsafe_report = build_canary_report(provider, unsafe_result)
    assert unsafe_report.final_status == "unsafe_terminal_response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            _response("interaction"),
            ValidationFailureReason.FUNCTION_CALL_COUNT,
        ),
        (
            _response("interaction", _call("unknown_function", {}, "call")),
            ValidationFailureReason.UNSUPPORTED_FUNCTION,
        ),
        (
            _response(
                "interaction", _call("get_provider_order", {"case_id": CANARY_CASE_ID}, "call")
            ),
            ValidationFailureReason.UNSUPPORTED_FUNCTION,
        ),
        (
            _response(
                "interaction",
                _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "call-one"),
                _call("get_verified_webhooks", {"case_id": CANARY_CASE_ID}, "call-two"),
            ),
            ValidationFailureReason.FUNCTION_CALL_COUNT,
        ),
        (
            _response("interaction", _call("get_truth_snapshot", "invalid-json-shape", "call")),
            ValidationFailureReason.TOOL_ARGUMENTS_SCHEMA_INVALID,
        ),
        (
            _response(
                "interaction",
                SimpleNamespace(type="function_call", name=None, arguments={}, id="call"),
            ),
            ValidationFailureReason.INVALID_FUNCTION_NAME,
        ),
        (
            _response("interaction", _call("abstain_investigation", "invalid-json-shape", "call")),
            ValidationFailureReason.TERMINAL_ARGUMENTS_NOT_OBJECT,
        ),
        (
            _response("interaction", _call("abstain_investigation", {}, "call")),
            ValidationFailureReason.TERMINAL_SCHEMA_INVALID,
        ),
        (
            _response("", _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "call")),
            ValidationFailureReason.MISSING_INTERACTION_ID,
        ),
        (
            _response("interaction", _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "")),
            ValidationFailureReason.MISSING_CALL_ID,
        ),
    ],
)
async def test_each_malformed_parser_branch_has_bounded_reason(
    response: object, reason: ValidationFailureReason
) -> None:
    provider, _ = _provider([response])
    report = await run_controlled_hydrogen_canary(provider)
    assert report.final_status == "malformed_model_output"
    assert report.requests_started == report.responses_received == 1
    assert report.turns[0].classification == "failed_safe"
    assert report.turns[0].validation_failure_reason is reason


@pytest.mark.asyncio
async def test_repeated_tool_and_wrong_arguments_stop_immediately() -> None:
    repeated_provider, _ = _provider(
        [
            _response("one", _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "one")),
            _response("two", _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "two")),
        ]
    )
    repeated = await run_controlled_hydrogen_canary(repeated_provider)
    assert repeated.final_status == "invalid_or_repeated_tool_request"
    assert repeated.requests_started == 2

    wrong_provider, _ = _provider(
        [
            _response(
                "one",
                _call(
                    "get_truth_snapshot",
                    {"case_id": "00000000-0000-4000-8000-000000000999"},
                    "one",
                ),
            )
        ]
    )
    wrong = await run_controlled_hydrogen_canary(wrong_provider)
    assert wrong.final_status == "malformed_model_output"
    assert wrong.requests_started == 1
    assert wrong.turns[0].validation_failure_reason is ValidationFailureReason.CASE_ID_MISMATCH


class FakeHttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("private raw provider error with secret and opaque request id")
        self.status_code = status_code
        self.response = SimpleNamespace(
            headers={"Retry-After": "7", "Authorization": "private-secret"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_reason", "status"),
    [
        (TimeoutError("private timeout"), "provider_timeout", None),
        (FakeHttpError(503), "provider_transient_provider", 503),
    ],
)
async def test_timeout_and_provider_error_stop_without_retry(
    error: BaseException,
    expected_reason: str,
    status: int | None,
) -> None:
    provider, client = _provider([error])
    report = await run_controlled_hydrogen_canary(provider)
    assert report.final_status == expected_reason
    assert report.requests_started == 1
    assert report.responses_received == 0
    assert report.retries == report.failover == 0
    assert len(client.interactions.requests) == 1
    assert report.turns[0].http_status == status
    saved = sanitized_report_json(report)
    assert "private" not in saved and "Authorization" not in saved and "request id" not in saved
    if status == 503:
        assert report.turns[0].quota_metadata == {"retry_after_seconds": 7}


@pytest.mark.asyncio
async def test_missing_or_duplicate_function_result_linkage_stops_before_transport() -> None:
    provider, client = _provider(
        [_response("one", _call("get_truth_snapshot", {"case_id": CANARY_CASE_ID}, "call-one"))]
    )
    request: dict[str, object] = {
        "objective": "controlled",
        "case": {"case_id": CANARY_CASE_ID},
        "tools": public_tool_catalog(),
        "observations": [],
    }
    first = await provider.next_turn(request)
    assert first.turn.action is InvestigationTurnAction.CALL_TOOL
    with pytest.raises(ValueError, match="missing or duplicated"):
        await provider.next_turn(request)
    duplicate = {
        **request,
        "observations": [
            {"tool": "get_truth_snapshot"},
            {"tool": "get_truth_snapshot"},
        ],
    }
    with pytest.raises(ValueError, match="missing or duplicated"):
        await provider.next_turn(duplicate)
    assert provider.request_starts == 1
    assert len(client.interactions.requests) == 1


@pytest.mark.asyncio
async def test_exact_three_start_ceiling_and_zero_application_tool_execution() -> None:
    names = [
        "get_truth_snapshot",
        "get_verified_webhooks",
        "get_internal_payment",
    ]
    provider = ScriptedProvider(
        [
            InvestigatorTurn(
                action=InvestigationTurnAction.CALL_TOOL,
                tool_name=name,
                tool_arguments={"case_id": CANARY_CASE_ID},
            )
            for name in names
        ]
    )
    scenario = FrozenInvestigationScenario(
        scenario_id="p17b-20",
        objective="Consume controlled evidence.",
        case_payload={"case_id": CANARY_CASE_ID},
        required_tools=(names[0],),
        expected_terminal="abstain",
        tool_observations={
            name: FrozenToolObservation(
                outcome="succeeded",
                evidence_ids=(f"evidence-{index}",),
                payload={"sequence": index},
            )
            for index, name in enumerate(names, 1)
        },
    )
    result = await run_frozen_scenario(provider, scenario, max_requests=MAX_REQUEST_STARTS)
    assert result.request_count == 3
    assert len(provider.requests) == 3
    assert result.terminal_reason == "request_budget_exhausted"

    module_source = (
        Path(runner.__file__).resolve().parents[1]
        / "app"
        / "evaluation"
        / "phase17b_gemini_hydrogen_canary.py"
    )
    source = module_source.read_text(encoding="utf-8")
    assert "execute_recovery_investigation_tool" not in source
    assert "AsyncSession" not in source


def test_artifact_redaction_and_source_receipt_checksum_guard(tmp_path: Path) -> None:
    provider, _ = _provider([])
    provider.request_starts = MAX_REQUEST_STARTS
    result = BenchmarkScenarioResult(
        scenario_id="p17b-18",
        selected_tools=(),
        terminal_action=None,
        request_count=MAX_REQUEST_STARTS,
        truth_compatible=False,
        required_tools_selected=False,
        citations_valid=False,
        abstention_correct=None,
        provider_failed=False,
        malformed_output=False,
        failed_safe=True,
        terminal_reason="request_budget_exhausted",
    )
    saved = sanitized_report_json(build_canary_report(provider, result))
    for forbidden in (
        "prompt",
        "observation",
        "raw_response",
        '"arguments":',
        "call_id",
        "interaction_id",
        "api_key",
        "Authorization",
    ):
        assert forbidden not in saved

    target = tmp_path / "source.json"
    target.write_text("changed", encoding="utf-8")
    original = runner.SOURCE_RECEIPT
    runner.SOURCE_RECEIPT = target
    try:
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            runner.verify_source_receipt()
    finally:
        runner.SOURCE_RECEIPT = original


@pytest.mark.asyncio
async def test_provider_refuses_fourth_start_before_transport() -> None:
    provider, client = _provider([])
    provider.request_starts = MAX_REQUEST_STARTS
    with pytest.raises(EvidenceInvestigatorProviderError, match="ceiling"):
        await provider.next_turn({})
    assert client.interactions.requests == []


def test_canary_model_is_allowlisted_and_propagated_without_prompt_or_linkage_changes() -> None:
    provider, _ = _provider([])
    flash_provider = HydrogenCanaryProvider(
        api_key="offline-test-key",
        model_name=GEMINI_35_FLASH_MODEL,
        client_factory=lambda _key, _timeout: FakeClient([]),
    )
    assert provider.model_name == "gemini-4-hydrogen"
    assert flash_provider.model_name == GEMINI_35_FLASH_MODEL
    with pytest.raises(ValueError, match="not allowlisted"):
        HydrogenCanaryProvider(
            api_key="offline-test-key",
            model_name="gemini-unknown",
            client_factory=lambda _key, _timeout: FakeClient([]),
        )


@pytest.mark.asyncio
async def test_runner_persists_report_before_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = tmp_path / "source.json"
    source.write_text("source-receipt", encoding="utf-8")
    destination = tmp_path / "canary-report.json"
    provider, _ = _provider([])
    result = BenchmarkScenarioResult(
        scenario_id="p17b-18",
        selected_tools=(),
        terminal_action=None,
        request_count=0,
        truth_compatible=False,
        required_tools_selected=False,
        citations_valid=False,
        abstention_correct=None,
        provider_failed=True,
        malformed_output=False,
        failed_safe=True,
        terminal_reason="provider_transient_provider",
    )
    report = build_canary_report(provider, result)

    class CleanupFailureProvider:
        async def aclose(self) -> None:
            assert destination.exists()
            raise RuntimeError("private cleanup detail")

    async def run_stub(_provider: object) -> object:
        return report

    monkeypatch.setattr(runner, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(runner, "SOURCE_RECEIPT", source)
    monkeypatch.setattr(runner, "LEASE_PATH", tmp_path / ".lease")
    monkeypatch.setattr(
        runner, "SOURCE_RECEIPT_SHA256", hashlib.sha256(source.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(runner, "load_isolated_key", lambda _path: "offline-test-key")
    monkeypatch.setattr(
        runner, "HydrogenCanaryProvider", lambda **_kwargs: CleanupFailureProvider()
    )
    monkeypatch.setattr(runner, "run_controlled_hydrogen_canary", run_stub)

    with caplog.at_level(logging.WARNING, logger=runner.__name__):
        returned = await runner.execute(destination, "gemini-4-hydrogen")

    assert returned == report
    assert (
        json.loads(destination.read_text(encoding="utf-8"))["final_status"] == report.final_status
    )
    assert "cleanup failed after report persistence" in caplog.text
    assert "private cleanup detail" not in caplog.text
