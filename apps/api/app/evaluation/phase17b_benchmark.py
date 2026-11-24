"""Isolated, deterministic scoring for the frozen Phase 17B investigator corpus."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProvider,
    EvidenceInvestigatorProviderError,
)
from app.services.recovery_investigation_tools import public_tool_catalog

TRUTH_COMPATIBILITY_THRESHOLD = 0.80
REQUIRED_TOOL_SELECTION_THRESHOLD = 0.80
CITATION_VALIDITY_THRESHOLD = 1.0
ABSTENTION_ACCURACY_THRESHOLD = 0.80
PROVIDER_FAILURE_THRESHOLD = 0.0
MALFORMED_OUTPUT_THRESHOLD = 0.0


class FrozenToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "unavailable"]
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    payload: dict[str, object]

    @model_validator(mode="after")
    def validate_evidence(self) -> FrozenToolObservation:
        if self.outcome == "succeeded" and not self.evidence_ids:
            raise ValueError("Successful frozen observations require evidence IDs")
        if self.outcome == "unavailable" and self.evidence_ids:
            raise ValueError("Unavailable frozen observations cannot claim evidence IDs")
        return self


class FrozenInvestigationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^p17b-[0-9]{2}$")
    objective: str = Field(min_length=1, max_length=300)
    case_payload: dict[str, object]
    required_tools: tuple[str, ...] = Field(min_length=1, max_length=8)
    expected_terminal: Literal["complete", "abstain"]
    expected_evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    forbidden_summary_fragments: tuple[str, ...] = Field(default=(), max_length=20)
    tool_observations: dict[str, FrozenToolObservation]

    @model_validator(mode="after")
    def validate_expectations(self) -> FrozenInvestigationScenario:
        case_id = self.case_payload.get("case_id")
        if not isinstance(case_id, str):
            raise ValueError("Frozen case payload requires a string UUID case_id")
        try:
            UUID(case_id)
        except ValueError as error:
            raise ValueError("Frozen case payload case_id must be a UUID") from error
        if not set(self.required_tools).issubset(self.tool_observations):
            raise ValueError("Every required tool needs a frozen observation")
        available_evidence = {
            evidence_id
            for observation in self.tool_observations.values()
            for evidence_id in observation.evidence_ids
        }
        if not set(self.expected_evidence_ids).issubset(available_evidence):
            raise ValueError("Expected evidence must be supplied by the frozen tools")
        return self


class FrozenInvestigationCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: Literal["reclaimrail-phase17b-v1", "reclaimrail-phase17b-v2"]
    evidence_mode: Literal["controlled_synthetic"]
    scenarios: tuple[FrozenInvestigationScenario, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> FrozenInvestigationCorpus:
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("Frozen scenario IDs must be unique")
        return self


@dataclass(frozen=True, slots=True)
class BenchmarkScenarioResult:
    scenario_id: str
    selected_tools: tuple[str, ...]
    terminal_action: str | None
    request_count: int
    truth_compatible: bool
    required_tools_selected: bool
    citations_valid: bool
    abstention_correct: bool | None
    provider_failed: bool
    malformed_output: bool
    failed_safe: bool
    terminal_reason: str
    provider_status_code: int | None = None
    provider_status: str | None = None
    provider_reason_code: str | None = None
    rate_limit_metadata: dict[str, object] | None = None
    diagnostic_receipts: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    corpus_id: str
    corpus_sha256: str
    scenario_results: tuple[BenchmarkScenarioResult, ...]
    truth_compatible_rate: float
    required_tool_selection_rate: float
    citation_validity_rate: float
    abstention_accuracy: float
    provider_failure_rate: float
    malformed_output_rate: float
    failed_safe_rate: float
    thresholds_passed: bool


def load_frozen_corpus(
    corpus_path: Path,
    checksum_path: Path,
) -> tuple[FrozenInvestigationCorpus, str]:
    payload = corpus_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    expected = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    if digest != expected:
        raise ValueError(f"Frozen corpus SHA-256 mismatch: expected {expected}, got {digest}")
    return FrozenInvestigationCorpus.model_validate_json(payload), digest


def _parse_turn(response: InvestigatorProviderResponse) -> InvestigatorTurn:
    if isinstance(response.turn, InvestigatorTurn):
        return response.turn
    if isinstance(response.turn, str):
        return InvestigatorTurn.model_validate_json(response.turn)
    return InvestigatorTurn.model_validate(response.turn)


async def run_frozen_scenario(
    provider: EvidenceInvestigatorProvider,
    scenario: FrozenInvestigationScenario,
    *,
    corpus_id: str = "reclaimrail-phase17b-v2",
    max_requests: int = 9,
) -> BenchmarkScenarioResult:
    observations: list[dict[str, object]] = []
    selected_tools: list[str] = []
    known_evidence: set[str] = set()
    request_count = 0
    tool_catalog = public_tool_catalog()
    allowed_tools = {str(tool["name"]) for tool in tool_catalog}

    while request_count < max_requests:
        request_count += 1
        try:
            response = await provider.next_turn(
                {
                    "benchmark": {
                        "corpus": corpus_id,
                        "scenario_id": scenario.scenario_id,
                        "evidence_mode": "controlled_synthetic",
                    },
                    "objective": scenario.objective,
                    "case": scenario.case_payload,
                    "tools": tool_catalog,
                    "observations": observations,
                    "budgets_remaining": {"tool_calls": 8 - len(selected_tools)},
                    "response_contract": "call one tool, complete with citations, or abstain",
                },
            )
        except EvidenceInvestigatorProviderError as error:
            malformed = error.kind is EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE
            return BenchmarkScenarioResult(
                scenario_id=scenario.scenario_id,
                selected_tools=tuple(selected_tools),
                terminal_action=None,
                request_count=request_count,
                truth_compatible=False,
                required_tools_selected=False,
                citations_valid=False,
                abstention_correct=None,
                provider_failed=not malformed,
                malformed_output=malformed,
                failed_safe=True,
                terminal_reason=(
                    "malformed_model_output" if malformed else f"provider_{error.kind.value}"
                ),
                provider_status_code=error.status_code,
                provider_status=error.provider_status,
                provider_reason_code=(error.reason_code.value if error.reason_code else None),
                rate_limit_metadata=(
                    error.rate_limit_metadata.as_dict() if error.rate_limit_metadata else None
                ),
            )
        except Exception as error:  # noqa: BLE001 - untrusted provider implementation
            return BenchmarkScenarioResult(
                scenario_id=scenario.scenario_id,
                selected_tools=tuple(selected_tools),
                terminal_action=None,
                request_count=request_count,
                truth_compatible=False,
                required_tools_selected=False,
                citations_valid=False,
                abstention_correct=None,
                provider_failed=True,
                malformed_output=False,
                failed_safe=True,
                terminal_reason=f"provider_unclassified:{type(error).__name__}",
            )

        if response.input_token_count is None or response.output_token_count is None:
            return BenchmarkScenarioResult(
                scenario_id=scenario.scenario_id,
                selected_tools=tuple(selected_tools),
                terminal_action=None,
                request_count=request_count,
                truth_compatible=False,
                required_tools_selected=False,
                citations_valid=False,
                abstention_correct=None,
                provider_failed=True,
                malformed_output=False,
                failed_safe=True,
                terminal_reason="usage_metadata_incomplete",
            )
        try:
            turn = _parse_turn(response)
        except Exception:  # noqa: BLE001 - strict schema boundary
            return BenchmarkScenarioResult(
                scenario_id=scenario.scenario_id,
                selected_tools=tuple(selected_tools),
                terminal_action=None,
                request_count=request_count,
                truth_compatible=False,
                required_tools_selected=False,
                citations_valid=False,
                abstention_correct=None,
                provider_failed=False,
                malformed_output=True,
                failed_safe=True,
                terminal_reason="malformed_model_output",
            )

        if turn.action is InvestigationTurnAction.CALL_TOOL:
            tool_name = turn.tool_name or ""
            expected_arguments = {"case_id": scenario.case_payload.get("case_id")}
            if (
                tool_name not in allowed_tools
                or tool_name in selected_tools
                or len(selected_tools) >= 8
                or turn.tool_arguments != expected_arguments
            ):
                return BenchmarkScenarioResult(
                    scenario_id=scenario.scenario_id,
                    selected_tools=tuple(selected_tools),
                    terminal_action=None,
                    request_count=request_count,
                    truth_compatible=False,
                    required_tools_selected=False,
                    citations_valid=False,
                    abstention_correct=None,
                    provider_failed=False,
                    malformed_output=True,
                    failed_safe=True,
                    terminal_reason="invalid_or_repeated_tool_request",
                )
            selected_tools.append(tool_name)
            observation = scenario.tool_observations.get(
                tool_name,
                FrozenToolObservation(
                    outcome="unavailable",
                    payload={"reason": "fixture_not_available"},
                ),
            )
            known_evidence.update(observation.evidence_ids)
            observations.append(
                {
                    "sequence": len(selected_tools),
                    "tool": tool_name,
                    "outcome": observation.outcome,
                    "evidence_ids": observation.evidence_ids,
                    "payload": observation.payload,
                },
            )
            continue

        cited = set(turn.evidence_ids)
        for hypothesis in turn.hypotheses:
            cited.update(hypothesis.supporting_evidence_ids)
            cited.update(hypothesis.contradicting_evidence_ids)
        citations_valid = cited.issubset(known_evidence)
        expected_action = InvestigationTurnAction(scenario.expected_terminal)
        terminal_matches = turn.action is expected_action
        expected_evidence_present = set(scenario.expected_evidence_ids).issubset(cited)
        summary = (turn.summary or turn.abstention_reason or "").lower()
        forbidden_absent = not any(
            fragment.lower() in summary for fragment in scenario.forbidden_summary_fragments
        )
        required_tools_selected = set(scenario.required_tools).issubset(selected_tools)
        abstention_correct = (
            terminal_matches if expected_action is InvestigationTurnAction.ABSTAIN else None
        )
        truth_compatible = (
            terminal_matches and expected_evidence_present and citations_valid and forbidden_absent
        )
        return BenchmarkScenarioResult(
            scenario_id=scenario.scenario_id,
            selected_tools=tuple(selected_tools),
            terminal_action=turn.action.value,
            request_count=request_count,
            truth_compatible=truth_compatible,
            required_tools_selected=required_tools_selected,
            citations_valid=citations_valid,
            abstention_correct=abstention_correct,
            provider_failed=False,
            malformed_output=False,
            failed_safe=forbidden_absent,
            terminal_reason="terminal_turn",
        )

    return BenchmarkScenarioResult(
        scenario_id=scenario.scenario_id,
        selected_tools=tuple(selected_tools),
        terminal_action=None,
        request_count=request_count,
        truth_compatible=False,
        required_tools_selected=False,
        citations_valid=False,
        abstention_correct=None,
        provider_failed=False,
        malformed_output=False,
        failed_safe=True,
        terminal_reason="request_budget_exhausted",
    )


async def run_frozen_corpus(
    provider: EvidenceInvestigatorProvider,
    corpus: FrozenInvestigationCorpus,
    corpus_sha256: str,
    *,
    request_budget: int,
) -> BenchmarkReport:
    if not 1 <= request_budget <= 100:
        raise ValueError("Phase 17B request budget must be between one and one hundred")
    remaining = request_budget
    results: list[BenchmarkScenarioResult] = []
    for scenario in corpus.scenarios:
        if remaining <= 0:
            raise RuntimeError("Phase 17B request budget was exhausted before the corpus completed")
        result = await run_frozen_scenario(
            provider,
            scenario,
            corpus_id=corpus.corpus_id,
            max_requests=min(9, remaining),
        )
        results.append(result)
        remaining -= result.request_count
    return build_benchmark_report(corpus, corpus_sha256, tuple(results))


def build_benchmark_report(
    corpus: FrozenInvestigationCorpus,
    corpus_sha256: str,
    results: tuple[BenchmarkScenarioResult, ...],
) -> BenchmarkReport:
    if len(results) != len(corpus.scenarios):
        raise ValueError("Benchmark report requires exactly one result per frozen scenario")
    count = len(results)
    abstentions = [
        result.abstention_correct for result in results if result.abstention_correct is not None
    ]

    def rate(passed: Iterable[bool], denominator: int = count) -> float:
        return sum(1 for value in passed if value) / denominator

    truth_rate = rate(result.truth_compatible for result in results)
    tool_rate = rate(result.required_tools_selected for result in results)
    citation_rate = rate(result.citations_valid for result in results)
    abstention_rate = rate(abstentions, len(abstentions)) if abstentions else 1.0
    provider_rate = rate(result.provider_failed for result in results)
    malformed_rate = rate(result.malformed_output for result in results)
    failed_safe_rate = rate(result.failed_safe for result in results)
    thresholds_passed = (
        truth_rate >= TRUTH_COMPATIBILITY_THRESHOLD
        and tool_rate >= REQUIRED_TOOL_SELECTION_THRESHOLD
        and citation_rate >= CITATION_VALIDITY_THRESHOLD
        and abstention_rate >= ABSTENTION_ACCURACY_THRESHOLD
        and provider_rate <= PROVIDER_FAILURE_THRESHOLD
        and malformed_rate <= MALFORMED_OUTPUT_THRESHOLD
    )
    return BenchmarkReport(
        corpus_id=corpus.corpus_id,
        corpus_sha256=corpus_sha256,
        scenario_results=results,
        truth_compatible_rate=truth_rate,
        required_tool_selection_rate=tool_rate,
        citation_validity_rate=citation_rate,
        abstention_accuracy=abstention_rate,
        provider_failure_rate=provider_rate,
        malformed_output_rate=malformed_rate,
        failed_safe_rate=failed_safe_rate,
        thresholds_passed=thresholds_passed,
    )


def sanitized_report_json(report: BenchmarkReport) -> str:
    return json.dumps(
        {
            "corpus_id": report.corpus_id,
            "corpus_sha256": report.corpus_sha256,
            "metrics": {
                "truth_compatible_rate": report.truth_compatible_rate,
                "required_tool_selection_rate": report.required_tool_selection_rate,
                "citation_validity_rate": report.citation_validity_rate,
                "abstention_accuracy": report.abstention_accuracy,
                "provider_failure_rate": report.provider_failure_rate,
                "malformed_output_rate": report.malformed_output_rate,
                "failed_safe_rate": report.failed_safe_rate,
            },
            "thresholds_passed": report.thresholds_passed,
            "scenarios": [
                {
                    "scenario_id": result.scenario_id,
                    "selected_tools": result.selected_tools,
                    "terminal_action": result.terminal_action,
                    "request_count": result.request_count,
                    "truth_compatible": result.truth_compatible,
                    "required_tools_selected": result.required_tools_selected,
                    "citations_valid": result.citations_valid,
                    "abstention_correct": result.abstention_correct,
                    "provider_failed": result.provider_failed,
                    "malformed_output": result.malformed_output,
                    "failed_safe": result.failed_safe,
                    "terminal_reason": result.terminal_reason,
                    "provider_status_code": result.provider_status_code,
                    "provider_status": result.provider_status,
                    "provider_reason_code": result.provider_reason_code,
                    "rate_limit_metadata": result.rate_limit_metadata,
                    "diagnostic_receipts": result.diagnostic_receipts,
                }
                for result in report.scenario_results
            ],
        },
        indent=2,
        sort_keys=True,
    )
