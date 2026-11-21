"""Offline command-boundary checks for the Groq-only frozen corpus runner."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.phase17b_benchmark import load_frozen_corpus
from app.evaluation.phase17b_groq_governor import (
    EVALUATION_TPD_CEILING,
    EVALUATION_TPM_CEILING,
    GovernedEvaluationProvider,
    GroqEvaluationGovernor,
    estimate_tokens,
    serialized_payload,
)
from app.integrations.gemini.evidence_investigator import INVESTIGATOR_SYSTEM_INSTRUCTION
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)
from scripts import run_phase17b_groq_benchmark as command

API_ROOT = Path(__file__).parents[1]
SCRIPT = API_ROOT / "scripts" / "run_phase17b_groq_benchmark.py"


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("RECLAIMRAIL_GROQ_API_KEY", None)
    return environment


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=API_ROOT,
        env=_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_direct_and_module_help_need_no_pythonpath_or_provider() -> None:
    for arguments in (
        [str(SCRIPT), "--help"],
        ["-m", "scripts.run_phase17b_groq_benchmark", "--help"],
    ):
        result = _run(arguments)
        assert result.returncode == 0
        assert "--acknowledge-live-groq" in result.stdout


def test_missing_acknowledgement_fails_before_provider_or_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    result = _run(
        [
            str(SCRIPT),
            "--corpus",
            "benchmarks/phase17b/corpus-v2.json",
            "--checksum",
            "benchmarks/phase17b/corpus-v2.sha256",
            "--output",
            str(output),
            "--acknowledge-live-groq",
            "wrong",
        ]
    )
    assert result.returncode != 0
    assert not output.exists()


def test_locked_output_rejects_existing_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", runtime)
    output = runtime / "report.json"
    runtime.mkdir(parents=True)
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        command._validate_destination(output)


class ScriptedFrozenProvider:
    def __init__(self, corpus: object) -> None:
        self.scenarios = {scenario.scenario_id: scenario for scenario in corpus.scenarios}  # type: ignore[attr-defined]
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    async def next_turn(self, request: dict[str, object]) -> object:
        self.calls += 1
        self.requests.append(request)
        scenario = self.scenarios[request["benchmark"]["scenario_id"]]  # type: ignore[index]
        observations = request["observations"]
        if len(observations) < len(scenario.required_tools):  # type: ignore[arg-type]
            tool = scenario.required_tools[len(observations)]  # type: ignore[index,arg-type]
            turn = {
                "action": "call_tool",
                "tool_name": tool,
                "tool_arguments": {"case_id": scenario.case_payload["case_id"]},
            }
        else:
            terminal = scenario.expected_terminal
            turn = {
                "action": terminal,
                "summary": "fixture terminal" if terminal == "complete" else None,
                "abstention_reason": "fixture abstention" if terminal == "abstain" else None,
                "evidence_ids": scenario.expected_evidence_ids,
            }
        return SimpleNamespace(
            turn=turn,
            model_name="openai/gpt-oss-120b",
            input_token_count=1,
            output_token_count=1,
            provider="groq",
            quota_metadata=None,
        )


@pytest.mark.asyncio
async def test_real_frozen_corpus_mock_success_writes_final_and_checkpoint(tmp_path: Path) -> None:
    corpus, digest = load_frozen_corpus(
        API_ROOT / "benchmarks/phase17b/corpus-v2.json",
        API_ROOT / "benchmarks/phase17b/corpus-v2.sha256",
    )
    assert digest == command.EXPECTED_CORPUS_SHA256
    now = 0.0

    def clock() -> float:
        return now

    async def sleeper(seconds: float) -> None:
        nonlocal now
        now += seconds

    fake = ScriptedFrozenProvider(corpus)
    metered = command.MeteredProvider(fake)
    output, checkpoint = tmp_path / "report.json", tmp_path / ".report.checkpoint.json"
    passed = await command.run_with_provider(
        corpus,
        digest,
        output,
        checkpoint,
        metered,
        GovernedEvaluationProvider(metered, GroqEvaluationGovernor(clock, sleeper)),
    )
    assert passed
    assert fake.calls == metered.request_starts == metered.responses_received == 31
    assert metered.requests_indeterminate == 0
    assert '"provider":"groq"' in output.read_text(encoding="utf-8")
    assert '"completed_scenarios"' in checkpoint.read_text(encoding="utf-8")
    schedule_governor = GroqEvaluationGovernor(clock, sleeper)
    schedule = tuple(
        [
            await schedule_governor.reserve(
                estimate_tokens(
                    serialized_payload(
                        request,
                        [
                            {"role": "system", "content": INVESTIGATOR_SYSTEM_INSTRUCTION},
                            {"role": "user", "content": json.dumps(request, sort_keys=True)},
                        ],
                    )
                )
            )
            for request in fake.requests
        ]
    )
    assert len(schedule) == 31
    assert sum(item.estimated_tokens for item in schedule) == 144_289
    assert (
        max(
            sum(
                candidate.estimated_tokens
                for candidate in schedule
                if reservation.at_seconds - 60 < candidate.at_seconds <= reservation.at_seconds
            )
            for reservation in schedule
        )
        == 4_699
    )
    assert sum(item.wait_seconds for item in schedule) == 1_800
    assert all(item.estimated_tokens <= EVALUATION_TPM_CEILING for item in schedule)
    assert sum(item.estimated_tokens for item in schedule) < EVALUATION_TPD_CEILING


@pytest.mark.asyncio
async def test_completed_threshold_failure_writes_complete_nonselecting_report(
    tmp_path: Path,
) -> None:
    corpus, digest = load_frozen_corpus(
        API_ROOT / "benchmarks/phase17b/corpus-v2.json",
        API_ROOT / "benchmarks/phase17b/corpus-v2.sha256",
    )
    fake = ScriptedFrozenProvider(corpus)
    original = fake.next_turn

    async def wrong_terminal(request: dict[str, object]) -> object:
        response = await original(request)
        if response.turn["action"] in {"complete", "abstain"}:
            response.turn["action"] = (
                "abstain" if response.turn["action"] == "complete" else "complete"
            )
            response.turn["summary"] = "wrong" if response.turn["action"] == "complete" else None
            response.turn["abstention_reason"] = (
                "wrong" if response.turn["action"] == "abstain" else None
            )
        return response

    fake.next_turn = wrong_terminal  # type: ignore[method-assign]

    async def sleeper(_: float) -> None:
        return None

    metered = command.MeteredProvider(fake)
    output, checkpoint = tmp_path / "failed.json", tmp_path / ".failed.checkpoint.json"
    selected = await command.run_with_provider(
        corpus,
        digest,
        output,
        checkpoint,
        metered,
        GovernedEvaluationProvider(metered, GroqEvaluationGovernor(lambda: 0.0, sleeper)),
    )
    assert not selected
    assert output.exists() and metered.request_starts == 31 and metered.responses_received == 31


@pytest.mark.asyncio
async def test_provider_failure_stops_after_checkpoint_with_sanitized_partial_progress(
    tmp_path: Path,
) -> None:
    corpus, digest = load_frozen_corpus(
        API_ROOT / "benchmarks/phase17b/corpus-v2.json",
        API_ROOT / "benchmarks/phase17b/corpus-v2.sha256",
    )
    fake = ScriptedFrozenProvider(corpus)
    original = fake.next_turn

    async def fail_on_fifth_request(request: dict[str, object]) -> object:
        if fake.calls == 4:
            fake.calls += 1
            fake.requests.append(request)
            raise EvidenceInvestigatorProviderError(
                "safe",
                kind=EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED,
                retryable=False,
                status_code=429,
            )
        return await original(request)

    fake.next_turn = fail_on_fifth_request  # type: ignore[method-assign]
    clock = 0.0

    def now() -> float:
        return clock

    async def sleeper(_: float) -> None:
        return None

    metered = command.MeteredProvider(fake)
    output, checkpoint = tmp_path / "report.json", tmp_path / ".report.checkpoint.json"
    selected = await command.run_with_provider(
        corpus,
        digest,
        output,
        checkpoint,
        metered,
        GovernedEvaluationProvider(metered, GroqEvaluationGovernor(now, sleeper)),
    )
    assert not selected
    assert fake.calls == metered.request_starts == 5
    assert metered.responses_received == 4 and metered.requests_indeterminate == 1
    assert not output.exists()
    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert checkpoint_payload["completed_scenarios"] == ["p17b-01", "p17b-02"]
    assert checkpoint_payload["retries"] == 0
    assert "safe" not in json.dumps(checkpoint_payload)
    receipt = checkpoint_payload["request_receipts"][-1]
    assert receipt["request_number"] == 5
    assert receipt["configured_timeout_seconds"] == 60.0
    assert receipt["scenario_id"] == "p17b-02"
    assert receipt["scenario_turn"] == 2
    assert receipt["failure_boundary"] == "provider_boundary"
    assert receipt["failure_classification"] == "quota_exhausted"
    assert receipt["provider_status_code"] == 429
    assert "rate_limit_metadata" not in receipt
    assert "objective" not in json.dumps(checkpoint_payload)


@pytest.mark.asyncio
async def test_failure_receipt_keeps_only_typed_provider_diagnostics(tmp_path: Path) -> None:
    class RejectedProvider:
        async def next_turn(self, request: dict[str, object]) -> object:
            raise EvidenceInvestigatorProviderError(
                "safe",
                kind=EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
                retryable=False,
                status_code=422,
                provider_status="private opaque provider text",
            )

    checkpoint = tmp_path / ".rejected.checkpoint.json"
    metered = command.MeteredProvider(RejectedProvider())
    metered.persist_receipt = lambda: command._checkpoint(checkpoint, metered, ())
    request = {
        "benchmark": {"scenario_id": "p17b-04"},
        "observations": [{"private": "evidence"}, {"private": "evidence"}],
        "objective": "private prompt content",
    }
    with pytest.raises(EvidenceInvestigatorProviderError):
        await metered.next_turn(request)
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    receipt = payload["request_receipts"][-1]
    assert receipt["scenario_id"] == "p17b-04"
    assert receipt["scenario_turn"] == 3
    assert receipt["provider_status_code"] == 422
    assert receipt["failure_classification"] == "provider_rejected"
    serialized = json.dumps(payload)
    assert "private" not in serialized
    assert "objective" not in serialized


@pytest.mark.asyncio
async def test_provider_exception_without_http_response_keeps_no_status(
    tmp_path: Path,
) -> None:
    class TransportFailureProvider:
        async def next_turn(self, request: dict[str, object]) -> object:
            raise EvidenceInvestigatorProviderError(
                "safe",
                kind=EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
                retryable=False,
            )

    checkpoint = tmp_path / ".transport.checkpoint.json"
    metered = command.MeteredProvider(TransportFailureProvider())
    metered.persist_receipt = lambda: command._checkpoint(checkpoint, metered, ())
    with pytest.raises(EvidenceInvestigatorProviderError):
        await metered.next_turn(
            {
                "benchmark": {"scenario_id": "p17b-04"},
                "observations": [],
            }
        )
    receipt = json.loads(checkpoint.read_text(encoding="utf-8"))["request_receipts"][-1]
    assert receipt["failure_classification"] == "transient_provider"
    assert receipt["scenario_id"] == "p17b-04"
    assert receipt["scenario_turn"] == 1
    assert "provider_status_code" not in receipt
    assert "provider_reason_code" not in receipt
    assert "rate_limit_metadata" not in receipt


@pytest.mark.asyncio
async def test_cancellation_persists_request_start_and_sanitized_failure_receipt(
    tmp_path: Path,
) -> None:
    class CancelledProvider:
        async def next_turn(self, request: dict[str, object]) -> object:
            raise asyncio.CancelledError()

    checkpoint = tmp_path / ".cancelled.checkpoint.json"
    metered = command.MeteredProvider(CancelledProvider())
    metered.persist_receipt = lambda: command._checkpoint(checkpoint, metered, ())
    with pytest.raises(asyncio.CancelledError):
        await metered.next_turn({"objective": "never persisted"})
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert (
        payload["requests_started"],
        payload["responses_received"],
        payload["requests_indeterminate"],
    ) == (1, 0, 1)
    assert payload["request_receipts"][-1]["failure_boundary"] == "process_cancellation"
    assert "never persisted" not in json.dumps(payload)


def test_checkpoint_replaces_atomically_and_final_report_is_write_once(tmp_path: Path) -> None:
    checkpoint = tmp_path / ".report.checkpoint.json"
    command._atomic_json(checkpoint, {"sequence": 1}, overwrite=True)
    command._atomic_json(checkpoint, {"sequence": 2}, overwrite=True)
    assert json.loads(checkpoint.read_text(encoding="utf-8")) == {"sequence": 2}
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(FileExistsError):
        command._atomic_json(checkpoint, {"sequence": 3}, overwrite=False)


def test_atomic_persistence_failure_leaves_no_partial_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "report.json"
    monkeypatch.setattr(command.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("safe")))
    with pytest.raises(OSError, match="safe"):
        command._atomic_json(destination, {"safe": True}, overwrite=False)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))
