from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.domain.investigation import (
    InvestigationBudgets,
    InvestigationStatus,
    InvestigationToolObservation,
    InvestigationToolOutcome,
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.services import recovery_investigator_service
from app.services.recovery_investigator_service import run_shadow_investigation

CASE_ID = UUID("93000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("93000000-0000-0000-0000-000000000002")
TRUTH_ID = UUID("93000000-0000-0000-0000-000000000003")
PAYMENT_ID = UUID("93000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


class ScriptedProvider:
    def __init__(self, turns: Sequence[InvestigatorTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, object]] = []

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        self.requests.append(request)
        return InvestigatorProviderResponse(
            turn=self.turns.pop(0),
            model_name="gemini-test",
            input_token_count=10,
            output_token_count=5,
        )


class RawProvider:
    def __init__(self, turn: object, *, input_tokens: int = 10, output_tokens: int = 5) -> None:
        self.turn = turn
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        self.calls += 1
        return InvestigatorProviderResponse(
            turn=self.turn,
            model_name="gemini-test",
            input_token_count=self.input_tokens,
            output_token_count=self.output_tokens,
        )


class FakeSession:
    def __init__(self, record: SimpleNamespace) -> None:
        self.record = record
        self.added: list[object] = []

    async def get(self, model: object, identity: object, **kwargs: object) -> object:
        return self.record

    async def scalar(self, statement: object) -> int:
        return self.record.case_version

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class FakeBegin:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSessionFactory:
    def __init__(self, record: SimpleNamespace) -> None:
        self.session = FakeSession(record)

    def begin(self) -> FakeBegin:
        return FakeBegin(self.session)


def make_record() -> SimpleNamespace:
    return SimpleNamespace(
        id=SESSION_ID,
        recovery_case_id=CASE_ID,
        payment_attempt_id=PAYMENT_ID,
        truth_snapshot_id=TRUTH_ID,
        case_version=7,
        truth_version=4,
        evidence_cutoff_at=NOW,
        status=InvestigationStatus.RUNNING.value,
        provider="gemini",
        model_name=None,
        model_version=None,
        prompt_version="evidence-investigator-v1",
        tool_registry_version="recovery-read-tools-v1",
        shadow_mode=True,
        tool_call_count=0,
        input_token_count=0,
        output_token_count=0,
        terminal_reason=None,
        result_summary=None,
        result_evidence_ids=[],
        result_digest=None,
        completed_at=None,
    )


def call(tool_name: str) -> InvestigatorTurn:
    return InvestigatorTurn(
        action=InvestigationTurnAction.CALL_TOOL,
        tool_name=tool_name,
        tool_arguments={"case_id": str(CASE_ID)},
    )


def complete(evidence_ids: tuple[str, ...]) -> InvestigatorTurn:
    return InvestigatorTurn(
        action=InvestigationTurnAction.COMPLETE,
        summary="Evidence supports a reviewer-visible conclusion.",
        evidence_ids=evidence_ids,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_sequence",
    [
        ("get_truth_snapshot", "get_verified_webhooks"),
        ("get_provider_payment", "get_internal_payment", "get_recovery_history"),
        ("get_provider_order", "get_route_health", "get_payment_link_status"),
    ],
)
async def test_three_cases_follow_different_live_tool_sequences(
    monkeypatch: pytest.MonkeyPatch,
    tool_sequence: tuple[str, ...],
) -> None:
    started_at = datetime.now(UTC)
    record = make_record()
    record.evidence_cutoff_at = started_at
    factory = FakeSessionFactory(record)
    evidence = tuple(f"evidence:{index}" for index in range(len(tool_sequence)))
    provider = ScriptedProvider([*(call(name) for name in tool_sequence), complete(evidence)])
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, True)),
    )
    monkeypatch.setattr(
        recovery_investigator_service,
        "_persist_hypotheses",
        AsyncMock(),
    )
    tool = AsyncMock(
        side_effect=[
            InvestigationToolObservation(
                tool_name=name,
                outcome=InvestigationToolOutcome.SUCCEEDED,
                evidence_ids=(evidence[index],),
                payload={"sequence": index + 1},
                started_at=started_at,
                completed_at=started_at,
            )
            for index, name in enumerate(tool_sequence)
        ],
    )
    monkeypatch.setattr(recovery_investigator_service, "execute_investigation_tool", tool)

    result = await run_shadow_investigation(
        factory,  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=provider,
        started_at=started_at,
    )

    assert result.status is InvestigationStatus.COMPLETED
    assert [call.kwargs["tool_name"] for call in tool.await_args_list] == list(tool_sequence)
    assert len(factory.session.added) == len(tool_sequence)
    assert all(step.tool_name in tool_sequence for step in factory.session.added)  # type: ignore[attr-defined]
    assert record.shadow_mode is True


@pytest.mark.asyncio
async def test_tool_budget_falls_back_without_executing_an_extra_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.now(UTC)
    record = make_record()
    record.evidence_cutoff_at = started_at
    factory = FakeSessionFactory(record)
    provider = ScriptedProvider([call("get_truth_snapshot"), call("get_verified_webhooks")])
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, True)),
    )
    monkeypatch.setattr(
        recovery_investigator_service,
        "_persist_hypotheses",
        AsyncMock(),
    )
    tool = AsyncMock(
        return_value=InvestigationToolObservation(
            tool_name="get_truth_snapshot",
            outcome=InvestigationToolOutcome.SUCCEEDED,
            evidence_ids=("truth:1",),
            payload={"state": "payment_failed"},
            started_at=started_at,
            completed_at=started_at,
        ),
    )
    monkeypatch.setattr(recovery_investigator_service, "execute_investigation_tool", tool)

    result = await run_shadow_investigation(
        factory,  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=provider,
        started_at=started_at,
        budgets=InvestigationBudgets(max_tool_calls=1),
    )

    assert result.status is InvestigationStatus.FALLBACK
    assert result.terminal_reason == "tool_budget_exhausted"
    assert tool.await_count == 1


@pytest.mark.asyncio
async def test_existing_case_version_returns_idempotently_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record()
    record.status = InvestigationStatus.ABSTAINED.value
    record.terminal_reason = "model_abstained"
    provider = ScriptedProvider([])
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, False)),
    )

    result = await run_shadow_investigation(
        FakeSessionFactory(record),  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=provider,
        started_at=NOW,
    )

    assert result.status is InvestigationStatus.ABSTAINED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_explicit_abstention_is_persisted_as_abstained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.now(UTC)
    record = make_record()
    record.evidence_cutoff_at = started_at
    factory = FakeSessionFactory(record)
    provider = ScriptedProvider(
        [
            InvestigatorTurn(
                action=InvestigationTurnAction.ABSTAIN,
                abstention_reason="Verified sources conflict.",
            ),
        ],
    )
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, True)),
    )
    monkeypatch.setattr(recovery_investigator_service, "_persist_hypotheses", AsyncMock())

    result = await run_shadow_investigation(
        factory,  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=provider,
        started_at=started_at,
    )

    assert result.status is InvestigationStatus.ABSTAINED
    assert result.terminal_reason == "model_abstained"
    assert result.result_summary == "Verified sources conflict."


@pytest.mark.asyncio
async def test_token_budget_and_malformed_output_fail_to_labelled_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.now(UTC)
    record = make_record()
    record.evidence_cutoff_at = started_at
    factory = FakeSessionFactory(record)
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, True)),
    )

    token_provider = RawProvider(call("get_truth_snapshot"), input_tokens=200, output_tokens=100)
    token_result = await run_shadow_investigation(
        factory,  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=token_provider,
        started_at=started_at,
        budgets=InvestigationBudgets(max_total_tokens=256),
    )
    assert token_result.status is InvestigationStatus.FALLBACK
    assert token_result.terminal_reason == "token_budget_exhausted"

    malformed_record = make_record()
    malformed_record.evidence_cutoff_at = started_at
    malformed_provider = RawProvider({"action": "complete"})
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(malformed_record, True)),
    )
    malformed_result = await run_shadow_investigation(
        FakeSessionFactory(malformed_record),  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=malformed_provider,
        started_at=started_at,
    )
    assert malformed_result.status is InvestigationStatus.FALLBACK
    assert malformed_result.terminal_reason.startswith("model_retry_budget_exhausted")
    assert malformed_provider.calls == 3


@pytest.mark.asyncio
async def test_unreturned_evidence_cannot_be_cited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.now(UTC)
    record = make_record()
    record.evidence_cutoff_at = started_at
    provider = RawProvider(complete(("future-or-cross-case-evidence",)))
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, True)),
    )

    result = await run_shadow_investigation(
        FakeSessionFactory(record),  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=provider,
        started_at=started_at,
    )

    assert result.status is InvestigationStatus.FALLBACK
    assert result.terminal_reason.startswith("model_retry_budget_exhausted")
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_unexpected_tool_failure_is_redacted_and_fails_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.now(UTC)
    record = make_record()
    record.evidence_cutoff_at = started_at
    monkeypatch.setattr(
        recovery_investigator_service,
        "_create_or_load_session",
        AsyncMock(return_value=(record, True)),
    )
    monkeypatch.setattr(recovery_investigator_service, "_persist_hypotheses", AsyncMock())
    monkeypatch.setattr(
        recovery_investigator_service,
        "execute_investigation_tool",
        AsyncMock(side_effect=RuntimeError("secret provider payload")),
    )

    result = await run_shadow_investigation(
        FakeSessionFactory(record),  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        provider=ScriptedProvider([call("get_provider_payment")]),
        started_at=started_at,
    )

    assert result.status is InvestigationStatus.FAILED_SAFE
    assert result.terminal_reason == "tool_failed:RuntimeError"
    assert "secret" not in (result.result_summary or "")
