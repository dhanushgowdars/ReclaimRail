from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.investigation import (
    InvestigationBudgets,
    InvestigationToolObservation,
    InvestigationToolOutcome,
    InvestigationTurnAction,
    InvestigatorTurn,
)
from app.integrations.gemini.evidence_investigator import build_investigator_prompt

NOW = datetime(2026, 9, 25, tzinfo=UTC)


def test_budgets_are_bounded_and_reject_unbounded_values() -> None:
    budget = InvestigationBudgets()
    assert budget.max_tool_calls == 8
    assert budget.max_model_retries == 2
    assert budget.max_duration == timedelta(seconds=30)

    with pytest.raises(ValueError, match="Tool-call budget"):
        InvestigationBudgets(max_tool_calls=21)
    with pytest.raises(ValueError, match="duration"):
        InvestigationBudgets(max_duration=timedelta(minutes=6))


def test_turn_contract_is_strict_and_supports_explicit_abstention() -> None:
    turn = InvestigatorTurn(
        action=InvestigationTurnAction.ABSTAIN,
        abstention_reason="Provider evidence conflicts and cannot support a conclusion.",
    )
    assert turn.action is InvestigationTurnAction.ABSTAIN

    with pytest.raises(ValidationError):
        InvestigatorTurn.model_validate(
            {"action": "complete", "summary": "unsupported", "evidence_ids": []},
        )
    with pytest.raises(ValidationError):
        InvestigatorTurn.model_validate(
            {"action": "abstain", "abstention_reason": "unknown", "extra": "forbidden"},
        )


def test_successful_observation_requires_ledger_citation_and_aware_time() -> None:
    observation = InvestigationToolObservation(
        tool_name="get_truth_snapshot",
        outcome=InvestigationToolOutcome.SUCCEEDED,
        evidence_ids=("truth:123",),
        payload={"state": "payment_failed"},
        started_at=NOW,
        completed_at=NOW,
    )
    assert observation.evidence_ids == ("truth:123",)

    with pytest.raises(ValueError, match="requires evidence"):
        InvestigationToolObservation(
            tool_name="get_truth_snapshot",
            outcome=InvestigationToolOutcome.SUCCEEDED,
            evidence_ids=(),
            payload={},
            started_at=NOW,
            completed_at=NOW,
        )


def test_prompt_does_not_accept_a_precomputed_deterministic_answer() -> None:
    request = {
        "objective": "Investigate evidence",
        "case": {"id": "case-1"},
        "observations": [],
    }
    prompt = build_investigator_prompt(request)
    assert "Investigate this recovery case" in prompt

    with pytest.raises(ValueError, match="cannot contain a deterministic answer"):
        build_investigator_prompt(
            {"case": {"deterministic_baseline": {"action": "create_payment_link"}}},
        )
