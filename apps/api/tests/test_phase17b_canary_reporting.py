from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.evaluation.phase17b_canary_reporting as reporting
from app.domain.investigation import InvestigationTurnAction
from app.evaluation.phase17b_groq_governor import GroqEvaluationGovernor
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)
from scripts.run_phase17b_groq_canary import canary_exit_code, run_and_write_report


def make_report(status: str = "success") -> reporting.CanaryTerminalReport:
    return reporting.terminal_report(
        status=status,
        model="openai/gpt-oss-120b",
        started_at=datetime.now(UTC),
        states=(reporting.CanaryStateReceipt(1, "truth", status),),
        requests_started=1,
        responses_received=1,
        requests_indeterminate=0,
    )


def test_write_once_sanitized_terminal_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(reporting, "RUNTIME_REPORT_DIRECTORY", runtime)
    target = runtime / "receipt.json"
    reporting.write_report_once(target, make_report())
    payload = target.read_text(encoding="utf-8")
    assert '"schema_version":"phase17b-groq-canary-v1"' in payload
    assert "tool_call_id" not in payload and "authorization" not in payload
    with pytest.raises(FileExistsError):
        reporting.write_report_once(target, make_report())


def test_writer_cleans_partial_file_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(reporting, "RUNTIME_REPORT_DIRECTORY", runtime)
    target = runtime / "receipt.json"
    monkeypatch.setattr(reporting.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError):
        reporting.write_report_once(target, make_report("internal_failure"))
    assert not target.exists()
    assert not list(runtime.glob("*.tmp"))


@pytest.mark.parametrize(
    "status",
    [
        "success",
        "governor_rejected",
        "provider_400",
        "provider_429",
        "provider_5xx",
        "transport_indeterminate",
        "malformed_response",
        "correlation_failed",
        "unexpected_turn",
        "invalid_terminal_schema",
        "internal_failure",
    ],
)
def test_every_controlled_outcome_is_terminal_and_sanitized(status: str) -> None:
    report = make_report(status)
    assert report.schema_version == reporting.REPORT_SCHEMA_VERSION
    assert report.sdk_attempts == report.requests_started
    assert report.retries == 0


class ScriptedProvider:
    def __init__(self, replies: list[object]) -> None:
        self.replies = replies

    async def next_turn(self, _: dict[str, object]) -> object:
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item  # type: ignore[return-value]


def _response(turn: object) -> object:
    return SimpleNamespace(
        turn=turn,
        model_name="openai/gpt-oss-120b",
        input_token_count=11,
        output_token_count=7,
        quota_metadata={"request_remaining": 29, "authorization": "forbidden"},
    )


def _governor() -> GroqEvaluationGovernor:
    async def sleeper(_: float) -> None:
        return None

    return GroqEvaluationGovernor(lambda: 0.0, sleeper)


@pytest.mark.asyncio
async def test_successful_three_state_report_is_sanitized_and_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(reporting, "RUNTIME_REPORT_DIRECTORY", runtime)
    from scripts import run_phase17b_groq_canary as command

    monkeypatch.setattr(command, "RUNTIME_REPORT_DIRECTORY", runtime)
    replies = [
        _response(
            SimpleNamespace(
                action=InvestigationTurnAction.CALL_TOOL,
                tool_name="get_truth_snapshot",
            )
        ),
        _response(
            SimpleNamespace(
                action=InvestigationTurnAction.CALL_TOOL,
                tool_name="get_verified_webhooks",
            )
        ),
        _response(SimpleNamespace(action=InvestigationTurnAction.COMPLETE, tool_name=None)),
    ]
    report = await run_and_write_report(
        provider=ScriptedProvider(replies),
        governor=_governor(),
        destination=runtime / "success.json",
    )
    assert report.run_status == "success"
    assert (report.requests_started, report.responses_received, report.requests_indeterminate) == (
        3,
        3,
        0,
    )
    assert report.sdk_attempts == 3 and report.retries == 0
    assert canary_exit_code(report) == 0
    payload = (runtime / "success.json").read_text(encoding="utf-8")
    assert "authorization" not in payload and "tool_call_id" not in payload
    assert "request_remaining" in payload


@pytest.mark.asyncio
async def test_provider_exception_after_start_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(reporting, "RUNTIME_REPORT_DIRECTORY", runtime)
    from scripts import run_phase17b_groq_canary as command

    monkeypatch.setattr(command, "RUNTIME_REPORT_DIRECTORY", runtime)
    error = EvidenceInvestigatorProviderError(
        "safe", kind=EvidenceInvestigatorFailureKind.TIMEOUT, retryable=False
    )
    report = await run_and_write_report(
        provider=ScriptedProvider([error]),
        governor=_governor(),
        destination=runtime / "timeout.json",
    )
    assert report.run_status == "transport_indeterminate"
    assert (report.requests_started, report.responses_received, report.requests_indeterminate) == (
        1,
        0,
        1,
    )
    assert (runtime / "timeout.json").exists()
    assert canary_exit_code(report) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status_code", "expected"),
    [
        (EvidenceInvestigatorFailureKind.PROVIDER_REJECTED, 400, "provider_400"),
        (EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED, 429, "provider_429"),
        (EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER, 503, "provider_5xx"),
        (EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE, None, "malformed_response"),
    ],
)
async def test_received_fail_closed_responses_are_terminal_and_not_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: EvidenceInvestigatorFailureKind,
    status_code: int | None,
    expected: str,
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(reporting, "RUNTIME_REPORT_DIRECTORY", runtime)
    from scripts import run_phase17b_groq_canary as command

    monkeypatch.setattr(command, "RUNTIME_REPORT_DIRECTORY", runtime)
    error = EvidenceInvestigatorProviderError(
        "safe", kind=kind, retryable=False, status_code=status_code
    )
    report = await run_and_write_report(
        provider=ScriptedProvider([error]),
        governor=_governor(),
        destination=runtime / f"{expected}.json",
    )
    assert report.run_status == expected
    assert (report.requests_started, report.responses_received, report.requests_indeterminate) == (
        1,
        1,
        0,
    )
    assert (runtime / f"{expected}.json").exists()
    assert canary_exit_code(report) == 1
    assert canary_exit_code(report) == 1


@pytest.mark.asyncio
async def test_governor_rejection_records_no_request_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "phase17b"
    monkeypatch.setattr(reporting, "RUNTIME_REPORT_DIRECTORY", runtime)
    from scripts import run_phase17b_groq_canary as command

    monkeypatch.setattr(command, "RUNTIME_REPORT_DIRECTORY", runtime)
    governor = _governor()
    governor.stopped = True
    report = await run_and_write_report(
        provider=ScriptedProvider([]), governor=governor, destination=runtime / "governor.json"
    )
    assert report.run_status == "governor_rejected"
    assert (report.requests_started, report.responses_received, report.requests_indeterminate) == (
        0,
        0,
        0,
    )
