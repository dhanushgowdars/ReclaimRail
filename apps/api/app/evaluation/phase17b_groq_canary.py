"""Three-turn controlled-synthetic Groq canary; never executes application tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import cast

from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.evaluation.phase17b_groq_governor import GovernedEvaluationProvider
from app.services.recovery_investigation_tools import public_tool_catalog

CANARY_CASE_ID = "00000000-0000-4000-8000-000000000018"
_STATES = (
    ("get_truth_snapshot",),
    ("get_verified_webhooks",),
    ("complete_investigation", "abstain_investigation"),
)


@dataclass(frozen=True, slots=True)
class CanaryReport:
    request_count: int
    first_correlation_valid: bool
    second_correlation_valid: bool
    terminal_schema_valid: bool
    terminal_action: str | None
    quota_metadata: tuple[dict[str, object] | None, ...]
    tool_execution_count: int = 0


def _request(observations: list[dict[str, object]], state: tuple[str, ...]) -> dict[str, object]:
    return {
        "canary": {"mode": "controlled_synthetic", "case_id": CANARY_CASE_ID},
        "objective": "Inspect only supplied synthetic evidence and take no action.",
        "case": {"id": CANARY_CASE_ID, "version": 0},
        "tools": public_tool_catalog(),
        "observations": observations,
        "_evaluation_forced_function_names": state,
    }


def _observation(turn: InvestigatorProviderResponse, sequence: int) -> dict[str, object]:
    parsed = cast(InvestigatorTurn, turn.turn)
    assert getattr(parsed, "tool_name", None)
    return {
        "sequence": sequence,
        "tool": parsed.tool_name,
        "outcome": "succeeded",
        "evidence_ids": (f"canary-evidence-{sequence}",),
        "payload": {"mode": "controlled_synthetic", "sequence": sequence},
    }


async def run_groq_canary(provider: GovernedEvaluationProvider) -> CanaryReport:
    observations: list[dict[str, object]] = []
    quotas: list[dict[str, object] | None] = []
    first = cast(
        InvestigatorProviderResponse, await provider.next_turn(_request(observations, _STATES[0]))
    )
    first_turn = cast(InvestigatorTurn, first.turn)
    if (
        first_turn.action is not InvestigationTurnAction.CALL_TOOL
        or first_turn.tool_name != _STATES[0][0]
    ):
        raise ValueError("canary first state did not return its forced read-only tool")
    quotas.append(first.quota_metadata)
    observations.append(_observation(first, 1))
    second = cast(
        InvestigatorProviderResponse, await provider.next_turn(_request(observations, _STATES[1]))
    )
    second_turn = cast(InvestigatorTurn, second.turn)
    if (
        second_turn.action is not InvestigationTurnAction.CALL_TOOL
        or second_turn.tool_name != _STATES[1][0]
    ):
        raise ValueError("canary second state did not return its forced read-only tool")
    quotas.append(second.quota_metadata)
    observations.append(_observation(second, 2))
    terminal = cast(
        InvestigatorProviderResponse, await provider.next_turn(_request(observations, _STATES[2]))
    )
    terminal_turn = cast(InvestigatorTurn, terminal.turn)
    if terminal_turn.action not in {
        InvestigationTurnAction.COMPLETE,
        InvestigationTurnAction.ABSTAIN,
    }:
        raise ValueError("canary terminal state did not return one terminal function")
    quotas.append(terminal.quota_metadata)
    return CanaryReport(3, True, True, True, terminal_turn.action.value, tuple(quotas))


def sanitized_canary_report_json(report: CanaryReport) -> str:
    import json

    return json.dumps(asdict(report), sort_keys=True)
