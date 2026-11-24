"""Owner-gated, evaluation-only Groq runner for the frozen Phase 17B corpus."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.domain.investigation import InvestigatorProviderResponse  # noqa: E402
from app.evaluation.phase17b_benchmark import (  # noqa: E402
    BenchmarkScenarioResult,
    FrozenInvestigationCorpus,
    build_benchmark_report,
    load_frozen_corpus,
    run_frozen_scenario,
    sanitized_report_json,
)
from app.evaluation.phase17b_groq_governor import (  # noqa: E402
    GovernedEvaluationProvider,
    GroqEvaluationGovernor,
)
from app.integrations.groq.evidence_investigator import (  # noqa: E402
    GROQ_EVALUATION_INSTRUCTION,
    GROQ_EVALUATION_PROMPT_VERSION,
    GroqEvidenceInvestigator,
)
from app.integrations.investigator import (  # noqa: E402
    EvidenceInvestigatorProvider,
    EvidenceInvestigatorProviderError,
)

MODEL = "openai/gpt-oss-120b"
LIVE_ACKNOWLEDGEMENT = "OWNER_APPROVED_PHASE17B_LIVE_GROQ"
MAX_REQUEST_STARTS = 31
LIVE_REQUEST_CEILING = 120
MIN_REQUEST_INTERVAL_SECONDS = 2.5
CONFIGURED_TIMEOUT_SECONDS = 60.0
EXPECTED_CORPUS_SHA256 = "814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de"
RUNTIME_DIRECTORY = API_ROOT.parents[1] / ".runtime" / "phase17b"
RUN_LOCK_NAME = ".groq-phase17b-corpus.lock"
_FROZEN_SCENARIO_ID = re.compile(r"^p17b-\d{2}$")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KEY = re.compile(r"(?i)\b(?:sk|rk|key|token|secret)[-_A-Za-z0-9]*\s*[:=]\s*[^\s,;]+")
_HEADER = re.compile(
    r"(?i)\b(?:authorization|x-api-key|api-key|cookie|set-cookie)\s*[:=]\s*[^\s,;]+"
)


def _scrub_text(value: object, limit: int = 300) -> str:
    text = _BEARER.sub("[REDACTED_BEARER]", str(value))
    text = _KEY.sub(
        lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=[REDACTED]", text
    )
    return _HEADER.sub("[REDACTED_HEADER]", text)[:limit]


def _safe_diagnostic_details(
    details: object, error: BaseException | None = None
) -> dict[str, object]:
    source = details if isinstance(details, dict) else {}
    safe: dict[str, object] = {}
    for key in (
        "http_status",
        "provider_error_code",
        "provider_error_type",
        "finish_reason",
        "turn_type",
        "local_validation_failure_reason_code",
    ):
        value = source.get(key)
        if isinstance(value, (str, int, float, bool)):
            safe[key] = _scrub_text(value, 120) if isinstance(value, str) else value
    for key in ("call_id", "tool_name"):
        if isinstance(source.get(key), str):
            safe[key] = _scrub_text(source[key], 256)
    if "arguments" in source:
        encoded = json.dumps(
            source["arguments"], sort_keys=True, separators=(",", ":"), default=str
        )
        safe["arguments"] = _scrub_text(encoded, 500)
    if source.get("scrubbed_error_message") is not None:
        safe["scrubbed_error_message"] = _scrub_text(source["scrubbed_error_message"], 300)
    for key, limit in (
        ("provider_error_code_raw", 120),
        ("provider_error_type_raw", 120),
        ("provider_error_message_raw", 300),
        ("failed_generation_raw", 500),
        ("x_request_id", 256),
        ("tool_declarations_sha256", 64),
    ):
        if isinstance(source.get(key), str):
            safe[key.removesuffix("_raw")] = _scrub_text(source[key], limit)
    if isinstance(source.get("parallel_tool_calls"), bool):
        safe["parallel_tool_calls"] = source["parallel_tool_calls"]
    if isinstance(source.get("tool_choice"), str):
        safe["tool_choice"] = _scrub_text(source["tool_choice"], 120)
    structure = source.get("message_structure")
    if isinstance(structure, list) and len(structure) <= 20:
        safe["message_structure"] = [
            {
                "role": _scrub_text(item.get("role"), 24),
                "tool_call_id": _scrub_text(item["tool_call_id"], 256)
                if isinstance(item.get("tool_call_id"), str)
                else None,
                "tool_call_ids": [
                    _scrub_text(call_id, 256)
                    for call_id in item.get("tool_call_ids", [])
                    if isinstance(call_id, str)
                ][:2],
                "content_length": item.get("content_length"),
            }
            for item in structure
            if isinstance(item, dict) and isinstance(item.get("content_length"), int)
        ]
    if isinstance(error, EvidenceInvestigatorProviderError):
        safe["turn_type"] = "provider_error"
        safe.setdefault("provider_error_type", error.kind.value)
        if error.status_code is not None:
            safe["http_status"] = error.status_code
        if error.reason_code is not None:
            safe["provider_error_code"] = error.reason_code.value
        safe.setdefault("scrubbed_error_message", "Groq evidence investigation failed safely")
    return safe


def _safe_request_context(request: dict[str, object]) -> dict[str, object]:
    """Retain only frozen-schedule coordinates, never prompt or evidence content."""
    benchmark = request.get("benchmark")
    observations = request.get("observations")
    if not isinstance(benchmark, dict) or not isinstance(observations, list):
        return {}
    scenario_id = benchmark.get("scenario_id")
    turn = len(observations) + 1
    if (
        not isinstance(scenario_id, str)
        or _FROZEN_SCENARIO_ID.fullmatch(scenario_id) is None
        or not 1 <= turn <= 9
    ):
        return {}
    return {"scenario_id": scenario_id, "scenario_turn": turn}


def _safe_provider_error(error: BaseException) -> dict[str, object]:
    """Extract only typed, allowlisted diagnostics from the provider boundary."""
    if not isinstance(error, EvidenceInvestigatorProviderError):
        return {}
    safe: dict[str, object] = {}
    if isinstance(error.status_code, int) and 100 <= error.status_code <= 599:
        safe["provider_status_code"] = error.status_code
    if error.reason_code is not None:
        safe["provider_reason_code"] = error.reason_code.value
    if error.rate_limit_metadata is not None:
        allowlisted = {
            "category",
            "request_limit",
            "request_remaining",
            "token_limit",
            "token_remaining",
            "request_reset_seconds",
            "token_reset_seconds",
            "retry_after_seconds",
        }
        metadata = {
            key: value
            for key, value in error.rate_limit_metadata.as_dict().items()
            if key in allowlisted and isinstance(value, (str, int, float, bool))
        }
        if metadata:
            safe["rate_limit_metadata"] = metadata
    return safe


@dataclass(slots=True)
class MeteredProvider:
    provider: TurnProvider
    request_starts: int = 0
    responses_received: int = 0
    requests_indeterminate: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    quota_metadata: list[dict[str, object]] = field(default_factory=list)
    receipts: list[dict[str, object]] = field(default_factory=list)
    persist_receipt: Callable[[], None] | None = None
    min_start_interval_seconds: float = 0.0
    maximum_starts: int = MAX_REQUEST_STARTS
    attempt_number: int = 1
    _last_start_monotonic: float | None = None

    def _persist(self) -> None:
        if self.persist_receipt is not None:
            self.persist_receipt()

    @staticmethod
    def _quota_metadata(metadata: dict[str, object] | None) -> dict[str, object] | None:
        if metadata is None:
            return None
        allowlisted = {
            "request_remaining",
            "requests_remaining",
            "tokens_remaining",
            "reset_seconds",
        }
        return {
            key: value
            for key, value in metadata.items()
            if key in allowlisted and isinstance(value, (str, int, float, bool))
        }

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        if self.request_starts >= self.maximum_starts:
            raise RuntimeError("frozen corpus request-start ceiling exceeded")
        now = time.monotonic()
        pacing_wait = 0.0
        if self._last_start_monotonic is not None:
            pacing_wait = max(
                0.0,
                self.min_start_interval_seconds - (now - self._last_start_monotonic),
            )
            if pacing_wait:
                await asyncio.sleep(pacing_wait)
        self._last_start_monotonic = time.monotonic()
        self.request_starts += 1
        started_at = datetime.now(UTC)
        started = time.monotonic()
        receipt: dict[str, object] = {
            "request_number": self.request_starts,
            "attempt_number": self.attempt_number,
            "request_started_at": started_at.isoformat(),
            "configured_timeout_seconds": CONFIGURED_TIMEOUT_SECONDS,
            "governor_admission": "admitted",
            "pacing_wait_seconds": round(pacing_wait, 3),
            **_safe_request_context(request),
        }
        self.receipts.append(receipt)
        self._persist()
        try:
            response = await self.provider.next_turn(request)
        except BaseException as error:
            self.requests_indeterminate += 1
            receipt.update(
                {
                    "failure_recorded_at": datetime.now(UTC).isoformat(),
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "failure_boundary": (
                        "process_cancellation"
                        if isinstance(error, asyncio.CancelledError)
                        else "provider_boundary"
                    ),
                    "failure_classification": (
                        getattr(getattr(error, "kind", None), "value", None)
                        or (
                            "cancelled"
                            if isinstance(error, asyncio.CancelledError)
                            else "indeterminate_transport"
                        )
                    ),
                    **_safe_provider_error(error),
                }
            )
            diagnostic = _safe_diagnostic_details(
                getattr(self.provider, "last_diagnostic_details", None), error
            )
            if diagnostic:
                receipt["diagnostic"] = diagnostic
            self._persist()
            raise
        self.responses_received += 1
        self.input_tokens += response.input_token_count or 0
        self.output_tokens += response.output_token_count or 0
        quota_metadata = self._quota_metadata(response.quota_metadata)
        if quota_metadata is not None:
            self.quota_metadata.append(quota_metadata)
        receipt.update(
            {
                "response_received_at": datetime.now(UTC).isoformat(),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "input_tokens": response.input_token_count,
                "output_tokens": response.output_token_count,
                "quota_metadata": quota_metadata,
            }
        )
        diagnostic = _safe_diagnostic_details(
            getattr(self.provider, "last_diagnostic_details", None)
        )
        if diagnostic:
            receipt["diagnostic"] = diagnostic
        self._persist()
        return response


class TurnProvider(Protocol):
    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse: ...


def _atomic_json(path: Path, payload: dict[str, object], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError("benchmark output destination already exists")
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        if not overwrite and path.exists():
            raise FileExistsError("benchmark output destination already exists")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_destination(path: Path) -> tuple[Path, Path]:
    output = path.resolve()
    if output.parent != RUNTIME_DIRECTORY.resolve() or output.suffix != ".json" or output.exists():
        raise ValueError(
            "benchmark output must be a new JSON report in the Phase 17B runtime directory"
        )
    checkpoint = output.with_name(f".{output.stem}.checkpoint.json")
    if checkpoint.exists():
        raise FileExistsError("benchmark checkpoint destination already exists")
    return output, checkpoint


@contextmanager
def _exclusive_run() -> Iterator[None]:
    RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
    lock = RUNTIME_DIRECTORY / RUN_LOCK_NAME
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write("phase17b corpus active\n")
    except FileExistsError:
        raise RuntimeError("another Phase 17B corpus run is active or needs inspection") from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _checkpoint(
    path: Path, provider: MeteredProvider, completed: tuple[BenchmarkScenarioResult, ...]
) -> None:
    _atomic_json(
        path,
        {
            "schema_version": "phase17b-groq-benchmark-checkpoint-v1",
            "provider": "groq",
            "model": MODEL,
            "completed_scenarios": [result.scenario_id for result in completed],
            "requests_started": provider.request_starts,
            "responses_received": provider.responses_received,
            "requests_indeterminate": provider.requests_indeterminate,
            "sdk_attempts": provider.request_starts,
            "retries": sum(receipt.get("attempt_number") == 2 for receipt in provider.receipts),
            "request_receipts": provider.receipts,
            "last_confirmed": (
                next(
                    (
                        receipt
                        for receipt in reversed(provider.receipts)
                        if "response_received_at" in receipt
                    ),
                    None,
                )
            ),
        },
        overwrite=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one owner-approved Groq frozen Phase 17B corpus."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-live-groq", required=True)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> bool:
    if args.acknowledge_live_groq != LIVE_ACKNOWLEDGEMENT:
        raise ValueError("Live Groq acknowledgement does not match the required owner token")
    output, checkpoint = _validate_destination(args.output)
    corpus, digest = load_frozen_corpus(args.corpus, args.checksum)
    if digest != EXPECTED_CORPUS_SHA256:
        raise ValueError("Groq benchmark requires the locked corpus-v2 SHA-256")
    with _exclusive_run():
        output, checkpoint = _validate_destination(args.output)
        settings = get_settings()
        key = settings.groq_api_key.get_secret_value().strip() if settings.groq_api_key else ""
        if not key:
            raise ValueError("Groq API access is not configured")

        async def sleeper(seconds: float) -> None:
            await asyncio.sleep(seconds)

        provider = MeteredProvider(
            GroqEvidenceInvestigator(
                api_key=key,
                model_name=MODEL,
                max_output_tokens=512,
                request_timeout_seconds=CONFIGURED_TIMEOUT_SECONDS,
            ),
            min_start_interval_seconds=MIN_REQUEST_INTERVAL_SECONDS,
            maximum_starts=LIVE_REQUEST_CEILING,
        )
        governed = GovernedEvaluationProvider(
            provider, GroqEvaluationGovernor(time.monotonic, sleeper)
        )
        return await run_with_provider(
            corpus, digest, output, checkpoint, provider, governed, LIVE_REQUEST_CEILING
        )


async def run_with_provider(
    corpus: FrozenInvestigationCorpus,
    digest: str,
    output: Path,
    checkpoint: Path,
    provider: MeteredProvider,
    governed: GovernedEvaluationProvider,
    max_request_starts: int = MAX_REQUEST_STARTS,
) -> bool:
    """Dependency-injected offline seam; production paths never call this."""
    results: list[BenchmarkScenarioResult] = []
    provider.persist_receipt = lambda: _checkpoint(checkpoint, provider, tuple(results))
    for scenario in corpus.scenarios:
        remaining = max_request_starts - provider.request_starts
        if remaining <= 0:
            break
        receipt_start = len(provider.receipts)
        result = await run_frozen_scenario(
            cast(EvidenceInvestigatorProvider, governed),
            scenario,
            corpus_id=corpus.corpus_id,
            max_requests=min(9, remaining),
        )
        result = replace(
            result,
            diagnostic_receipts=tuple(provider.receipts[receipt_start:]),
        )
        results.append(result)
        _checkpoint(checkpoint, provider, tuple(results))
    report = build_benchmark_report(corpus, digest, tuple(results))
    payload = json.loads(sanitized_report_json(report))
    for scenario_payload in payload["scenarios"]:
        receipts = scenario_payload["diagnostic_receipts"]
        scenario_payload["first_attempt_outcomes"] = [
            {
                "request_number": receipt["request_number"],
                "outcome": receipt.get("failure_classification", "response_received"),
            }
            for receipt in receipts
            if receipt.get("attempt_number") == 1
        ]
        scenario_payload["final_outcome"] = scenario_payload["terminal_reason"]
    payload["run"] = {
        "provider": "groq",
        "model": MODEL,
        "prompt_version": GROQ_EVALUATION_PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(GROQ_EVALUATION_INSTRUCTION.encode()).hexdigest(),
        "generated_at": datetime.now(UTC).isoformat(),
        "requests_started": provider.request_starts,
        "responses_received": provider.responses_received,
        "requests_indeterminate": provider.requests_indeterminate,
        "sdk_attempts": provider.request_starts,
        "retries": sum(receipt.get("attempt_number") == 2 for receipt in provider.receipts),
        "input_tokens": provider.input_tokens,
        "output_tokens": provider.output_tokens,
        "quota_metadata": provider.quota_metadata,
    }
    _atomic_json(output, payload, overwrite=False)
    return report.thresholds_passed


def main() -> None:
    raise SystemExit(0 if asyncio.run(run(parse_args())) else 1)


if __name__ == "__main__":
    main()
