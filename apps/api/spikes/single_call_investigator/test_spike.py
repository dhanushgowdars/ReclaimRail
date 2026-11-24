"""Mocked tests for the isolated single-call investigator spike."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.evaluation.phase17b_benchmark import load_frozen_corpus
from spikes.single_call_investigator.spike import (
    SYSTEM_INSTRUCTION,
    ModelFacingClaim,
    ModelFacingResult,
    RawStructuredResponse,
    RequestBudget,
    ScenarioScore,
    SingleCallAction,
    SingleCallGeminiProvider,
    SingleCallResult,
    ValidationFailureReason,
    _status_code,
    build_report,
    gather_evidence_bundle,
    gemini_response_schema,
    run_scenarios,
    sanitized_report_json,
    score_output,
    to_internal_result,
)

BENCHMARK_DIR = Path(__file__).parents[2] / "benchmarks" / "phase17b"


def corpus():
    return load_frozen_corpus(
        BENCHMARK_DIR / "corpus-v2.json",
        BENCHMARK_DIR / "corpus-v2.sha256",
    )[0]


def perfect_output(scenario) -> SingleCallResult:
    if scenario.expected_terminal == "complete":
        return SingleCallResult(
            action=SingleCallAction.COMPLETE,
            summary="The cited bounded evidence supports this conclusion.",
            evidence_ids=scenario.expected_evidence_ids,
        )
    return SingleCallResult(
        action=SingleCallAction.ABSTAIN,
        abstention_reason="The cited evidence is insufficient or conflicting.",
        evidence_ids=scenario.expected_evidence_ids,
    )


def perfect_model_output(scenario) -> ModelFacingResult:
    text = (
        "The cited bounded evidence supports this conclusion."
        if scenario.expected_terminal == "complete"
        else "The cited evidence is insufficient or conflicting."
    )
    return ModelFacingResult(
        verdict=SingleCallAction(scenario.expected_terminal),
        claims=(
            ModelFacingClaim(
                text=text,
                evidence_ids=scenario.expected_evidence_ids,
            ),
        ),
    )


class PerfectTransport:
    def __init__(self, scenarios) -> None:
        self._scenarios = {scenario.scenario_id: scenario for scenario in scenarios}
        self.models: list[str] = []

    async def generate(self, *, model: str, prompt: str, response_schema: dict[str, object]):
        self.models.append(model)
        scenario = next(
            scenario for scenario_id, scenario in self._scenarios.items() if scenario_id in prompt
        )
        assert response_schema["additionalProperties"] is False
        return RawStructuredResponse(
            text=perfect_model_output(scenario).model_dump_json(),
            served_model=model,
            input_tokens=10,
            output_tokens=5,
        )


@pytest.mark.asyncio
async def test_full_frozen_corpus_perfect_mock_meets_existing_thresholds() -> None:
    frozen = corpus()
    provider = SingleCallGeminiProvider(
        transport=PerfectTransport(frozen.scenarios),
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(60),
    )

    report = await run_scenarios(provider, frozen.scenarios)

    assert report.requests_used == 5
    assert len(report.scenario_scores) == 10
    assert all(score.passed for score in report.scenario_scores)
    assert report.thresholds_met is True
    assert report.citation_validity_rate == 1.0
    assert report.abstention_accuracy == 1.0


@pytest.mark.asyncio
async def test_precheck_abstains_without_model_for_unavailable_or_conflicting_evidence() -> None:
    frozen = corpus()
    scenarios = [frozen.scenarios[index] for index in (1, 2, 7)]
    transport = PerfectTransport(scenarios)
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(8),
    )

    report = await run_scenarios(provider, scenarios)

    assert report.requests_used == 0
    assert transport.models == []
    assert all(score.decision_source == "precheck" for score in report.scenario_scores)
    assert all(score.passed for score in report.scenario_scores)
    assert "Unavailable required evidence or unresolved conflicts require abstention." in (
        SYSTEM_INSTRUCTION
    )


def test_evidence_gathering_is_deterministic_bounded_and_uses_required_tools_only() -> None:
    scenario = corpus().scenarios[0]
    first = gather_evidence_bundle(scenario)
    second = gather_evidence_bundle(scenario)

    assert first == second
    assert [item.tool for item in first.observations] == list(scenario.required_tools)
    assert first.evidence_ids == frozenset(scenario.expected_evidence_ids)


def test_model_facing_schema_is_small_flat_and_every_array_is_bounded() -> None:
    schema = gemini_response_schema()

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert {"anyOf", "$defs", "$ref", "minLength", "maxLength", "pattern", "default"}.isdisjoint(
        keys(schema)
    )

    def arrays(value: object) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        if isinstance(value, dict):
            if value.get("type") == "array":
                found.append(value)
            for item in value.values():
                found.extend(arrays(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(arrays(item))
        return found

    assert arrays(schema)
    assert all("maxItems" in array for array in arrays(schema))


def test_model_output_converts_to_full_internal_schema_and_enforces_limits() -> None:
    scenario = corpus().scenarios[0]
    internal = to_internal_result(perfect_model_output(scenario))
    assert internal.action is SingleCallAction.COMPLETE
    assert internal.evidence_ids == scenario.expected_evidence_ids
    with pytest.raises(ValidationError, match="at most 600"):
        SingleCallResult(
            action=SingleCallAction.COMPLETE,
            summary="x" * 601,
            evidence_ids=("evidence-1",),
        )


@pytest.mark.parametrize(
    ("output", "expected_reason"),
    [
        (
            SingleCallResult(
                action=SingleCallAction.COMPLETE,
                summary="Bounded conclusion.",
                evidence_ids=("unknown-evidence",),
            ),
            ValidationFailureReason.CITATION_UNKNOWN.value,
        ),
        (
            SingleCallResult(
                action=SingleCallAction.ABSTAIN,
                abstention_reason="Insufficient.",
                evidence_ids=("truth-01", "webhook-01"),
            ),
            ValidationFailureReason.TERMINAL_MISMATCH.value,
        ),
    ],
)
def test_validation_rejects_unknown_citations_and_wrong_terminal(
    output: SingleCallResult,
    expected_reason: str,
) -> None:
    scenario = corpus().scenarios[0]
    bundle = gather_evidence_bundle(scenario)
    score = score_output(
        scenario,
        bundle,
        SimpleNamespace(
            output=output,
            requested_model="gemini-primary",
            served_model="mock",
            transport_starts=1,
            decision_source="model",
            requested_models=("gemini-primary",),
            http_status=None,
            exception_type=None,
            sanitized_error_message=None,
            model_answer_served=True,
            model_output_malformed=False,
        ),
    )

    assert score.passed is False
    assert expected_reason in score.validation_failure_reasons


class FakeHttpError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__("private provider payload")
        self.status_code = status_code
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        self.response = SimpleNamespace(headers=headers)


class ServerError(Exception):
    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ClientError(Exception):
    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ServerError(503, "high demand"), 503),
        (ClientError(429, "quota exhausted"), 429),
        (ServerError(None, "Model unavailable; try again later"), 503),
        (ClientError(None, "Rate limit quota reached"), 429),
    ],
)
def test_google_sdk_errors_map_code_and_safe_message_to_retry_status(
    error: BaseException,
    expected: int,
) -> None:
    assert _status_code(error) == expected


class ScriptedTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.models: list[str] = []

    async def generate(self, *, model: str, prompt: str, response_schema: dict[str, object]):
        self.models.append(model)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


async def record_sleep(delays: list[float], delay: float) -> None:
    delays.append(delay)


@pytest.mark.asyncio
async def test_retry_after_then_fallback_remains_one_structured_call_per_attempt() -> None:
    scenario = corpus().scenarios[0]
    success = RawStructuredResponse(
        text=perfect_model_output(scenario).model_dump_json(),
        served_model="gemini-fallback",
        input_tokens=10,
        output_tokens=5,
    )
    transport = ScriptedTransport(
        [
            FakeHttpError(503, "4"),
            FakeHttpError(429),
            FakeHttpError(503, "0"),
            success,
        ]
    )
    delays: list[float] = []
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(6),
        sleep=lambda delay: record_sleep(delays, delay),
        jitter=lambda: 0.5,
    )

    report = await run_scenarios(provider, [scenario])

    assert transport.models == ["gemini-primary"] * 3 + ["gemini-fallback"]
    assert delays == [4.0, 2.0]
    assert report.requests_used == 4
    assert report.scenario_scores[0].served_model == "gemini-fallback"
    assert report.scenario_scores[0].requested_model == "gemini-fallback"
    assert report.scenario_scores[0].passed is True


@pytest.mark.asyncio
async def test_timeout_retries_twice_then_uses_fallback() -> None:
    scenario = corpus().scenarios[0]
    success = RawStructuredResponse(
        text=perfect_model_output(scenario).model_dump_json(),
        served_model="gemini-fallback",
        input_tokens=10,
        output_tokens=5,
    )
    transport = ScriptedTransport([TimeoutError(), TimeoutError(), TimeoutError(), success])
    delays: list[float] = []
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(8),
        sleep=lambda delay: record_sleep(delays, delay),
        jitter=lambda: 0.5,
    )

    report = await run_scenarios(provider, [scenario])

    assert transport.models == ["gemini-primary"] * 3 + ["gemini-fallback"]
    assert delays == [1.0, 2.0]
    assert report.requests_used == 4
    assert report.scenario_scores[0].served_model == "gemini-fallback"


@pytest.mark.asyncio
async def test_two_fallback_models_are_attempted_in_order() -> None:
    scenario = corpus().scenarios[0]
    success = RawStructuredResponse(
        text=perfect_model_output(scenario).model_dump_json(),
        served_model="gemini-final-fallback",
        input_tokens=10,
        output_tokens=5,
    )
    transport = ScriptedTransport([FakeHttpError(503)] * 6 + [success])
    delays: list[float] = []
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(9),
        sleep=lambda delay: record_sleep(delays, delay),
        jitter=lambda: 0.5,
    )

    report = await run_scenarios(provider, [scenario])

    assert transport.models == (
        ["gemini-primary"] * 3 + ["gemini-fallback"] * 3 + ["gemini-final-fallback"]
    )
    assert report.requests_used == 7
    assert report.scenario_scores[0].served_model == "gemini-final-fallback"
    assert report.scenario_scores[0].requested_models == tuple(transport.models)
    assert delays == [1.0, 2.0, 1.0, 2.0]


@pytest.mark.asyncio
async def test_retry_after_and_jitter_are_capped_at_sixty_seconds() -> None:
    scenario = corpus().scenarios[0]
    success = RawStructuredResponse(
        text=perfect_model_output(scenario).model_dump_json(),
        served_model="gemini-primary",
        input_tokens=10,
        output_tokens=5,
    )
    transport = ScriptedTransport([FakeHttpError(503, "90"), success])
    delays: list[float] = []
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(3),
        sleep=lambda delay: record_sleep(delays, delay),
        jitter=lambda: 1.0,
    )

    report = await run_scenarios(provider, [scenario])

    assert report.scenario_scores[0].passed is True
    assert delays == [60.0]


@pytest.mark.asyncio
async def test_exhausted_model_path_uses_correct_deterministic_fallback() -> None:
    scenario = corpus().scenarios[0]
    transport = ScriptedTransport([FakeHttpError(503)] * 9)
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(9),
        sleep=lambda delay: record_sleep([], delay),
        jitter=lambda: 0.5,
    )

    report = await run_scenarios(provider, [scenario])

    score = report.scenario_scores[0]
    assert score.passed is True
    assert score.decision_source == "deterministic_fallback"
    assert score.provider_failed is True
    assert report.model_correctness_when_served is None
    assert report.model_availability_rate == 0.0
    assert report.truth_compatible_rate == 1.0
    assert report.citation_validity_rate == 1.0
    assert report.thresholds_met is False


@pytest.mark.asyncio
async def test_empty_verified_model_chain_uses_deterministic_fallback_without_request() -> None:
    scenario = corpus().scenarios[0]
    transport = ScriptedTransport([])
    provider = SingleCallGeminiProvider(
        transport=transport,
        models=(),
        budget=RequestBudget(9),
    )

    report = await run_scenarios(provider, [scenario])

    score = report.scenario_scores[0]
    assert transport.models == []
    assert report.requests_used == 0
    assert score.passed is True
    assert score.decision_source == "deterministic_fallback"
    assert score.requested_models == ()
    assert score.exception_type == "NoVerifiedModel"
    assert report.model_correctness_when_served is None
    assert report.model_availability_rate == 0.0


@pytest.mark.asyncio
async def test_scenario_gap_applies_between_prechecked_scenarios_only() -> None:
    frozen = corpus()
    scenarios = [frozen.scenarios[index] for index in (1, 2, 7)]
    delays: list[float] = []
    provider = SingleCallGeminiProvider(
        transport=PerfectTransport(scenarios),
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(1),
    )

    report = await run_scenarios(
        provider,
        scenarios,
        scenario_gap_seconds=lambda: 4.0,
        sleep=lambda delay: record_sleep(delays, delay),
    )

    assert all(score.decision_source == "precheck" for score in report.scenario_scores)
    assert delays == [4.0, 4.0]


@pytest.mark.asyncio
async def test_report_separates_requested_model_from_provider_served_version() -> None:
    scenario = corpus().scenarios[0]
    transport = ScriptedTransport(
        [
            RawStructuredResponse(
                text=perfect_model_output(scenario).model_dump_json(),
                served_model="gemini-3.6-flash",
                input_tokens=10,
                output_tokens=5,
            )
        ]
    )
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-3.5-flash",
        fallback_model="gemini-4-hydrogen",
        final_fallback_model="gemini-2.5-flash",
        budget=RequestBudget(6),
    )

    report = await run_scenarios(provider, [scenario])

    score = report.scenario_scores[0]
    assert score.requested_model == "gemini-3.5-flash"
    assert score.served_model == "gemini-3.6-flash"


@pytest.mark.asyncio
async def test_schema_failure_uses_deterministic_fallback_and_breaks_thresholds() -> None:
    scenario = corpus().scenarios[0]
    transport = ScriptedTransport(
        [RawStructuredResponse("{}", model, 1, 1) for model in ("one", "two", "three")]
    )
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(6),
    )

    report = await run_scenarios(provider, [scenario])

    score = report.scenario_scores[0]
    assert score.validation_failure_reasons == ()
    assert score.passed is True
    assert score.decision_source == "deterministic_fallback"
    assert score.malformed_output is True
    assert report.model_correctness_when_served == 0.0
    assert score.failed_safe is True
    assert report.thresholds_met is False


@pytest.mark.asyncio
async def test_provider_failure_retains_only_bounded_sanitized_diagnostics() -> None:
    scenario = corpus().scenarios[0]
    transport = ScriptedTransport(
        [
            FakeHttpError(
                400,
            )
        ]
    )
    transport.responses[0].args = (  # type: ignore[union-attr]
        "Invalid schema case_id=00000000-0000-4000-8000-000000000001 "
        "api_key=private-secret evidence_bundle=private",
    )
    provider = SingleCallGeminiProvider(
        transport=transport,
        primary_model="gemini-primary",
        fallback_model="gemini-fallback",
        final_fallback_model="gemini-final-fallback",
        budget=RequestBudget(6),
    )

    report = await run_scenarios(provider, [scenario])

    score = report.scenario_scores[0]
    assert score.http_status == 400
    assert score.exception_type == "FakeHttpError"
    assert score.requested_model == "gemini-primary"
    assert score.sanitized_error_message == "Provider request failed with status=400"
    serialized = sanitized_report_json(report)
    assert "private-secret" not in serialized
    assert scenario.case_payload["case_id"] not in serialized


def test_report_contains_no_prompt_key_or_raw_provider_payload() -> None:
    report = build_report(
        [
            ScenarioScore(
                scenario_id="p17b-01",
                passed=False,
                validation_failure_reasons=("provider_failure",),
                requested_model="gemini-primary",
                requested_models=("gemini-primary",),
                served_model=None,
                transport_starts=1,
                truth_compatible=False,
                required_tools_selected=True,
                citations_valid=False,
                abstention_correct=None,
                provider_failed=True,
                malformed_output=False,
                failed_safe=True,
                http_status=400,
                exception_type="FakeHttpError",
                sanitized_error_message="Provider request failed with status=400",
                decision_source="model",
                model_answer_correct=None,
            )
        ],
        requests_used=1,
    )
    serialized = sanitized_report_json(report)
    assert "api_key" not in serialized
    assert "prompt" not in serialized
    assert "private provider payload" not in serialized
