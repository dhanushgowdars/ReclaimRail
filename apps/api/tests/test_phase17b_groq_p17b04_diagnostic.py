"""Offline safety checks for the bounded p17b-04 Groq diagnostic wrapper."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

from app.domain.investigation import InvestigatorProviderResponse
from app.evaluation.phase17b_groq_governor import (
    EVALUATION_TPD_CEILING,
    GovernedEvaluationProvider,
    GroqEvaluationGovernor,
)
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    EvidenceInvestigatorProviderReason,
)
from app.services.recovery_investigation_tools import public_tool_catalog
from scripts import run_phase17b_groq_p17b04_diagnostic as command
from scripts.run_phase17b_groq_benchmark import MeteredProvider

API_ROOT = Path(__file__).parents[1]
SCRIPT = API_ROOT / "scripts" / "run_phase17b_groq_p17b04_diagnostic.py"


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _response(turn: dict[str, object]) -> InvestigatorProviderResponse:
    return InvestigatorProviderResponse(
        turn=turn,
        model_name=command.MODEL,
        input_token_count=2,
        output_token_count=1,
        provider="groq",
    )


def _governed(
    provider: object,
    governor: GroqEvaluationGovernor | None = None,
) -> tuple[MeteredProvider, GovernedEvaluationProvider]:
    fake_time = FakeTime()
    metered = MeteredProvider(provider)  # type: ignore[arg-type]
    capped = command.ThreeStartProvider(metered)
    return metered, GovernedEvaluationProvider(
        capped,
        governor or GroqEvaluationGovernor(fake_time.clock, fake_time.sleep),
    )


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return (
        tmp_path / "groq-p17b-04-diagnostic-test.json",
        tmp_path / ".groq-p17b-04-diagnostic-test.checkpoint.json",
    )


def _tool_turn(scenario: object, name: str) -> dict[str, object]:
    return {
        "action": "call_tool",
        "tool_name": name,
        "tool_arguments": {"case_id": scenario.case_payload["case_id"]},  # type: ignore[attr-defined,index]
    }


def test_locked_scenario_and_checksum_are_fixed() -> None:
    scenario, digest = command._load_locked_scenario()

    assert scenario.scenario_id == "p17b-04"
    assert digest == command.EXPECTED_CORPUS_SHA256
    assert command.CORPUS_PATH.name == "corpus-v2.json"
    assert command.CHECKSUM_PATH.name == "corpus-v2.sha256"
    assert command.MAX_REQUEST_STARTS == 3


@pytest.mark.asyncio
async def test_preflight_guards_fail_before_credentials_or_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    touched_credentials = False

    def forbidden_settings() -> object:
        nonlocal touched_credentials
        touched_credentials = True
        raise AssertionError("credentials must not load")

    monkeypatch.setattr(command, "get_settings", forbidden_settings)
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", tmp_path)
    output = tmp_path / "groq-p17b-04-diagnostic-guard.json"
    wrong_budget = command.parse_args(
        [
            "--output",
            str(output),
            "--acknowledge-starting-budget",
            "42/150",
            "--acknowledge-live-groq",
            command.LIVE_ACKNOWLEDGEMENT,
        ]
    )
    with pytest.raises(ValueError, match="41/150"):
        await command.run(wrong_budget)
    wrong_live = command.parse_args(
        [
            "--output",
            str(output),
            "--acknowledge-starting-budget",
            command.STARTING_BUDGET_ACKNOWLEDGEMENT,
            "--acknowledge-live-groq",
            "budget-is-not-live-authorization",
        ]
    )
    with pytest.raises(ValueError, match="live Groq acknowledgement"):
        await command.run(wrong_live)
    assert not touched_credentials
    assert not output.exists()


def test_destination_requires_new_ignored_runtime_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", tmp_path)
    output = tmp_path / "groq-p17b-04-diagnostic-v1.json"
    resolved, checkpoint = command._validate_destination(output)
    assert resolved == output.resolve()
    assert checkpoint.name == ".groq-p17b-04-diagnostic-v1.checkpoint.json"

    output.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        command._validate_destination(output)
    output.unlink()
    checkpoint.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        command._validate_destination(output)
    with pytest.raises(ValueError):
        command._validate_destination(tmp_path / "selection-report.json")


def test_exclusive_lease_blocks_concurrent_invocation_without_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", tmp_path)
    output = tmp_path / "groq-p17b-04-diagnostic-concurrent.json"
    checkpoint = tmp_path / ".groq-p17b-04-diagnostic-concurrent.checkpoint.json"
    lock = tmp_path / command.RUN_LOCK_NAME

    with command._exclusive_run():
        assert lock.read_text(encoding="utf-8") == "p17b-04 diagnostic active\n"
        output.write_text("first invocation output", encoding="utf-8")
        checkpoint.write_text("first invocation checkpoint", encoding="utf-8")
        with pytest.raises(command.DiagnosticAlreadyRunningError), command._exclusive_run():
            raise AssertionError("concurrent invocation must not enter")
        assert output.read_text(encoding="utf-8") == "first invocation output"
        assert checkpoint.read_text(encoding="utf-8") == "first invocation checkpoint"
    assert not lock.exists()


@pytest.mark.asyncio
async def test_active_or_stale_lease_fails_before_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", tmp_path)
    lock = tmp_path / command.RUN_LOCK_NAME
    lock.write_text("operator inspection required\n", encoding="utf-8")
    credentials_loaded = False

    def forbidden_settings() -> object:
        nonlocal credentials_loaded
        credentials_loaded = True
        raise AssertionError("credentials must not load while the lease exists")

    monkeypatch.setattr(command, "get_settings", forbidden_settings)
    args = command.parse_args(
        [
            "--output",
            str(tmp_path / "groq-p17b-04-diagnostic-blocked.json"),
            "--acknowledge-starting-budget",
            command.STARTING_BUDGET_ACKNOWLEDGEMENT,
            "--acknowledge-live-groq",
            command.LIVE_ACKNOWLEDGEMENT,
        ]
    )
    with pytest.raises(command.DiagnosticAlreadyRunningError):
        await command.run(args)
    assert not credentials_loaded
    assert lock.read_text(encoding="utf-8") == "operator inspection required\n"


@pytest.mark.asyncio
async def test_natural_turns_use_model_selected_frozen_observations(tmp_path: Path) -> None:
    scenario, digest = command._load_locked_scenario()
    model_selected = tuple(scenario.tool_observations)

    class NaturalProvider:
        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            observations = request["observations"]
            assert isinstance(observations, list)
            self.requests.append({**request, "observations": list(observations)})
            if len(observations) < len(model_selected):
                return _response(_tool_turn(scenario, model_selected[len(observations)]))
            return _response(
                {
                    "action": scenario.expected_terminal,
                    "summary": "late authorization stops continued recovery",
                    "evidence_ids": scenario.expected_evidence_ids,
                }
            )

    fake = NaturalProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    completed = await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )

    assert completed
    assert metered.request_starts == 3
    assert [len(request["observations"]) for request in fake.requests] == [0, 1, 2]  # type: ignore[arg-type]
    for index, name in enumerate(model_selected):
        observation = fake.requests[index + 1]["observations"][index]  # type: ignore[index]
        assert observation["tool"] == name
        assert observation["payload"] == scenario.tool_observations[name].payload
    assert all("_evaluation_forced_function_names" not in request for request in fake.requests)
    serialized = output.read_text(encoding="utf-8")
    assert all(name not in serialized for name in model_selected)


@pytest.mark.asyncio
async def test_early_terminal_response_stops_without_spending_three_starts(
    tmp_path: Path,
) -> None:
    scenario, digest = command._load_locked_scenario()

    class EarlyTerminalProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            return _response(
                {
                    "action": "abstain",
                    "abstention_reason": "No evidence was observed before this safe abstention.",
                    "evidence_ids": (),
                }
            )

    fake = EarlyTerminalProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    assert await command.run_with_provider(scenario, digest, output, checkpoint, metered, governed)
    assert fake.calls == metered.request_starts == 1


@pytest.mark.asyncio
async def test_unseen_terminal_citations_fail_closed_and_stay_sanitized(
    tmp_path: Path,
) -> None:
    scenario, digest = command._load_locked_scenario()
    private_summary = "private terminal summary with unseen citations"

    class UnseenCitationProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            return _response(
                {
                    "action": "complete",
                    "summary": private_summary,
                    "evidence_ids": scenario.expected_evidence_ids,
                }
            )

    fake = UnseenCitationProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    assert fake.calls == metered.request_starts == 1
    for path in (output, checkpoint):
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload)
        assert payload["result"]["diagnostic_status"] == "unsafe_terminal_response"
        assert payload["result"]["citations_valid"] is False
        assert private_summary not in serialized
        assert all(evidence_id not in serialized for evidence_id in scenario.expected_evidence_ids)


@pytest.mark.asyncio
async def test_forbidden_terminal_summary_fails_closed_and_stays_sanitized(
    tmp_path: Path,
) -> None:
    scenario, digest = command._load_locked_scenario()
    model_selected = tuple(scenario.tool_observations)
    forbidden_summary = f"Recommendation: {scenario.forbidden_summary_fragments[0]}."

    class ForbiddenSummaryProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            observations = request["observations"]
            assert isinstance(observations, list)
            self.calls += 1
            if len(observations) < len(model_selected):
                return _response(_tool_turn(scenario, model_selected[len(observations)]))
            return _response(
                {
                    "action": "complete",
                    "summary": forbidden_summary,
                    "evidence_ids": scenario.expected_evidence_ids,
                }
            )

    fake = ForbiddenSummaryProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    assert fake.calls == metered.request_starts == 3
    for path in (output, checkpoint):
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload)
        assert payload["result"]["diagnostic_status"] == "unsafe_terminal_response"
        assert payload["result"]["citations_valid"] is True
        assert payload["result"]["failed_safe"] is False
        assert forbidden_summary not in serialized


@pytest.mark.asyncio
async def test_three_start_ceiling_records_incomplete_not_selection(tmp_path: Path) -> None:
    scenario, digest = command._load_locked_scenario()
    selected = tuple(str(item["name"]) for item in public_tool_catalog())[:3]

    class NonTerminalProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            observations = request["observations"]
            assert isinstance(observations, list)
            self.calls += 1
            return _response(_tool_turn(scenario, selected[len(observations)]))

    fake = NonTerminalProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    completed = await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert not completed
    assert fake.calls == metered.request_starts == 3
    assert payload["result"]["diagnostic_status"] == "incomplete_request_ceiling"
    assert payload["corpus_verdict"] == "not_evaluated"
    assert payload["model_selection"] == "not_evaluated"
    assert "thresholds_passed" not in payload
    assert "truth_compatible_rate" not in json.dumps(payload)
    with pytest.raises(command.DiagnosticStartCeilingError):
        await command.ThreeStartProvider(metered).next_turn({})
    assert fake.calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_start", [1, 2, 3])
async def test_provider_failure_on_each_start_stops_without_retry(
    failure_start: int, tmp_path: Path
) -> None:
    scenario, digest = command._load_locked_scenario()
    selected = tuple(scenario.tool_observations)

    class FailingProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            if self.calls == failure_start:
                raise EvidenceInvestigatorProviderError(
                    "private provider response",
                    kind=EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
                    retryable=False,
                    status_code=422,
                )
            observations = request["observations"]
            assert isinstance(observations, list)
            return _response(_tool_turn(scenario, selected[len(observations)]))

    fake = FailingProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert fake.calls == metered.request_starts == failure_start
    assert payload["retries"] == 0 and payload["failover"] is False
    assert payload["result"]["diagnostic_status"] == "provider_or_governor_failure"


@pytest.mark.asyncio
async def test_governor_refusal_stops_before_transport(tmp_path: Path) -> None:
    scenario, digest = command._load_locked_scenario()

    class ForbiddenTransport:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> object:
            self.calls += 1
            raise AssertionError("transport must not start")

    fake_time = FakeTime()
    governor = GroqEvaluationGovernor(fake_time.clock, fake_time.sleep)
    governor.day_events.append((0.0, EVALUATION_TPD_CEILING))
    fake = ForbiddenTransport()
    metered, governed = _governed(fake, governor)
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert fake.calls == metered.request_starts == 0
    assert payload["result"]["diagnostic_status"] == "provider_or_governor_failure"


@pytest.mark.asyncio
async def test_malformed_output_stops_after_one_start(tmp_path: Path) -> None:
    scenario, digest = command._load_locked_scenario()

    class MalformedProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            return _response({"action": "complete"})

    fake = MalformedProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert fake.calls == metered.request_starts == 1
    assert payload["result"]["diagnostic_status"] == "malformed_output"


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_kind", ["unknown", "wrong_arguments", "repeated"])
async def test_unsafe_tool_or_arguments_stop_at_first_invalid_turn(
    unsafe_kind: str, tmp_path: Path
) -> None:
    scenario, digest = command._load_locked_scenario()
    selected = tuple(scenario.tool_observations)

    class UnsafeProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            if unsafe_kind == "unknown":
                return _response(_tool_turn(scenario, "not_an_investigator_tool"))
            if unsafe_kind == "wrong_arguments":
                turn = _tool_turn(scenario, selected[0])
                turn["tool_arguments"] = {"case_id": "00000000-0000-4000-8000-000000000099"}
                return _response(turn)
            return _response(_tool_turn(scenario, selected[0]))

    fake = UnsafeProvider()
    metered, governed = _governed(fake)
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    expected_calls = 2 if unsafe_kind == "repeated" else 1
    assert fake.calls == metered.request_starts == expected_calls
    assert payload["result"]["diagnostic_status"] == "unsafe_turn"


@pytest.mark.asyncio
async def test_artifacts_retain_only_allowlisted_typed_receipts(tmp_path: Path) -> None:
    scenario, digest = command._load_locked_scenario()

    class PrivateFailureProvider:
        async def next_turn(self, request: dict[str, object]) -> object:
            raise EvidenceInvestigatorProviderError(
                "secret credential and raw response body",
                kind=EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
                retryable=False,
                status_code=422,
                provider_status="opaque-provider-status-and-header",
                reason_code=EvidenceInvestigatorProviderReason.INVALID_ARGUMENT,
            )

    metered, governed = _governed(PrivateFailureProvider())
    output, checkpoint = _paths(tmp_path)
    assert not await command.run_with_provider(
        scenario, digest, output, checkpoint, metered, governed
    )
    for path in (output, checkpoint):
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload)
        assert "secret credential" not in serialized
        assert "raw response body" not in serialized
        assert "opaque-provider-status" not in serialized
        assert str(scenario.case_payload["case_id"]) not in serialized
        assert scenario.objective not in serialized
        assert all(name not in serialized for name in scenario.tool_observations)
        receipt = payload["request_receipts"][-1]
        assert receipt["scenario_id"] == "p17b-04"
        assert receipt["scenario_turn"] == 1
        assert receipt["provider_status_code"] == 422
        assert receipt["provider_reason_code"] == "invalid_argument"


@pytest.mark.asyncio
async def test_cancellation_after_start_leaves_only_sanitized_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, digest = command._load_locked_scenario()
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", tmp_path)

    class CancelledProvider:
        async def next_turn(self, request: dict[str, object]) -> object:
            raise asyncio.CancelledError()

    metered, governed = _governed(CancelledProvider())
    output, checkpoint = _paths(tmp_path)
    with pytest.raises(asyncio.CancelledError), command._exclusive_run():
        await command.run_with_provider(scenario, digest, output, checkpoint, metered, governed)
    assert metered.request_starts == 1
    assert metered.responses_received == 0
    assert metered.requests_indeterminate == 1
    assert not output.exists()
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["result"] is None
    receipt = payload["request_receipts"][-1]
    assert receipt["failure_boundary"] == "process_cancellation"
    assert receipt["failure_classification"] == "cancelled"
    assert not (tmp_path / command.RUN_LOCK_NAME).exists()
    serialized = json.dumps(payload)
    assert scenario.objective not in serialized
    assert str(scenario.case_payload["case_id"]) not in serialized


@pytest.mark.asyncio
async def test_diagnostic_details_are_retained_and_secrets_headers_are_scrubbed(
    tmp_path: Path,
) -> None:
    scenario, digest = command._load_locked_scenario()

    class DetailedProvider:
        last_diagnostic_details = {
            "http_status": 400,
            "provider_error_code": "INVALID_ARGUMENT",
            "provider_error_type": "provider_rejected",
            "scrubbed_error_message": (
                "Bearer sk-live=secret key=topsecret x-api-key: leaked invalid function arguments"
            ),
            "tool_name": "get_truth_snapshot",
            "arguments": {"case_id": "safe-id", "token": "Bearer abc"},
            "call_id": "call_opaque_1",
            "finish_reason": "tool_calls",
            "turn_type": "call_tool",
            "local_validation_failure_reason_code": "provider_boundary_error",
        }

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            return _response({"action": "complete", "evidence_ids": ()})

    metered = command.DiagnosticMeteredProvider(DetailedProvider())
    output, checkpoint = _paths(tmp_path)
    fake_time = FakeTime()
    governed = GovernedEvaluationProvider(
        command.ThreeStartProvider(metered),
        GroqEvaluationGovernor(fake_time.clock, fake_time.sleep),
    )
    await command.run_with_provider(scenario, digest, output, checkpoint, metered, governed)
    payload = json.loads(output.read_text(encoding="utf-8"))
    diagnostic = payload["request_receipts"][0]["diagnostic"]
    assert diagnostic["http_status"] == 400
    assert diagnostic["provider_error_code"] == "INVALID_ARGUMENT"
    assert diagnostic["tool_name"] == "get_truth_snapshot"
    assert diagnostic["call_id"] == "call_opaque_1"
    assert len(diagnostic["arguments"]) <= 500
    serialized = json.dumps(payload)
    assert "sk-live" not in serialized
    assert "topsecret" not in serialized
    assert "Bearer abc" not in serialized
    assert "x-api-key" not in serialized
    assert "headers" not in diagnostic
    assert payload["corpus_verdict"] == "not_evaluated"
    assert payload["model_selection"] == "not_evaluated"


def test_wrapper_has_no_forced_call_id_or_prohibited_runtime_import() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    prohibited = ("gemini", "razorpay", ".db", ".workers", "recovery_investigation_tools")

    assert not any(fragment in name for name in imports for fragment in prohibited)
    assert "_evaluation_forced_function_names" not in source
    assert "tool_call_id" not in source
    assert "build_benchmark_report" not in source
    assert "thresholds_passed" not in source
