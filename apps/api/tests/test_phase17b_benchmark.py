from collections.abc import Sequence
from pathlib import Path

import pytest

from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.evaluation.phase17b_benchmark import (
    FrozenInvestigationCorpus,
    build_benchmark_report,
    load_frozen_corpus,
    run_frozen_scenario,
    sanitized_report_json,
)
from app.integrations.gemini.evidence_investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    EvidenceInvestigatorProviderReason,
)

BENCHMARK_DIR = Path(__file__).parents[1] / "benchmarks" / "phase17b"


class ScenarioPerfectProvider:
    def __init__(self, required_tools: Sequence[str], terminal: InvestigatorTurn) -> None:
        self._required_tools = list(required_tools)
        self._terminal = terminal
        self.calls = 0

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        self.calls += 1
        if self._required_tools:
            case_payload = request["case"]
            assert isinstance(case_payload, dict)
            turn = InvestigatorTurn(
                action=InvestigationTurnAction.CALL_TOOL,
                tool_name=self._required_tools.pop(0),
                tool_arguments={"case_id": case_payload["case_id"]},
            )
        else:
            turn = self._terminal
        return InvestigatorProviderResponse(
            turn=turn,
            model_name="deterministic-script",
            model_version="deterministic-script-v1",
            input_token_count=10,
            output_token_count=5,
        )


@pytest.mark.asyncio
async def test_frozen_corpus_and_locked_thresholds_pass_for_perfect_script() -> None:
    corpus, digest = load_frozen_corpus(
        BENCHMARK_DIR / "corpus-v2.json",
        BENCHMARK_DIR / "corpus-v2.sha256",
    )
    results = []
    for scenario in corpus.scenarios:
        if scenario.expected_terminal == "complete":
            terminal = InvestigatorTurn(
                action=InvestigationTurnAction.COMPLETE,
                summary="Evidence supports only the cited read-only conclusion.",
                evidence_ids=scenario.expected_evidence_ids,
            )
        else:
            terminal = InvestigatorTurn(
                action=InvestigationTurnAction.ABSTAIN,
                abstention_reason="Evidence is insufficient or contradictory.",
                evidence_ids=scenario.expected_evidence_ids,
            )
        results.append(
            await run_frozen_scenario(
                ScenarioPerfectProvider(scenario.required_tools, terminal),
                scenario,
            ),
        )

    report = build_benchmark_report(corpus, digest, tuple(results))

    assert report.thresholds_passed is True
    assert report.truth_compatible_rate == 1.0
    assert report.required_tool_selection_rate == 1.0
    assert report.citation_validity_rate == 1.0
    assert report.abstention_accuracy == 1.0
    assert report.provider_failure_rate == 0.0
    assert report.malformed_output_rate == 0.0
    assert '"evidence_mode"' not in sanitized_report_json(report)


def test_frozen_corpus_refuses_checksum_mismatch(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.json"
    checksum_path = tmp_path / "corpus.sha256"
    corpus_path.write_text('{"tampered":true}', encoding="utf-8")
    checksum_path.write_text("0" * 64, encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_frozen_corpus(corpus_path, checksum_path)


@pytest.mark.asyncio
async def test_malformed_output_is_counted_once_without_hidden_retry() -> None:
    corpus, _ = load_frozen_corpus(
        BENCHMARK_DIR / "corpus-v2.json",
        BENCHMARK_DIR / "corpus-v2.sha256",
    )

    class MalformedProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            self.calls += 1
            return InvestigatorProviderResponse(
                turn={"action": "complete"},
                model_name="malformed-script",
                input_token_count=1,
                output_token_count=1,
            )

    provider = MalformedProvider()
    result = await run_frozen_scenario(provider, corpus.scenarios[0])

    assert result.malformed_output is True
    assert result.failed_safe is True
    assert result.request_count == 1
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_provider_rejection_retains_only_safe_diagnostic_codes() -> None:
    corpus, _ = load_frozen_corpus(
        BENCHMARK_DIR / "corpus-v2.json",
        BENCHMARK_DIR / "corpus-v2.sha256",
    )

    class RejectedProvider:
        async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
            raise EvidenceInvestigatorProviderError(
                "private provider payload with a credential",
                kind=EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
                retryable=False,
                status_code=400,
                provider_status="INVALID_ARGUMENT",
                reason_code=EvidenceInvestigatorProviderReason.INVALID_ARGUMENT,
            )

    result = await run_frozen_scenario(RejectedProvider(), corpus.scenarios[0])
    assert result.provider_status_code == 400
    assert result.provider_status == "INVALID_ARGUMENT"
    assert result.provider_reason_code == "invalid_argument"

    report = build_benchmark_report(corpus, "safe-digest", (result,) * len(corpus.scenarios))
    serialized = sanitized_report_json(report)
    assert "private provider payload" not in serialized
    assert "credential" not in serialized


def test_legacy_v1_corpus_is_retained_but_rejected_before_provider_use() -> None:
    payload = (BENCHMARK_DIR / "corpus-v1.json").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="case_id must be a UUID"):
        FrozenInvestigationCorpus.model_validate_json(payload)
