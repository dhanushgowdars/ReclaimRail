"""Owner-gated, evaluation-only Groq runner for the frozen Phase 17B corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
from app.integrations.groq.evidence_investigator import GroqEvidenceInvestigator  # noqa: E402
from app.integrations.investigator import (  # noqa: E402
    EvidenceInvestigatorProvider,
    EvidenceInvestigatorProviderError,
)

MODEL = "openai/gpt-oss-120b"
LIVE_ACKNOWLEDGEMENT = "OWNER_APPROVED_PHASE17B_LIVE_GROQ"
MAX_REQUEST_STARTS = 31
CONFIGURED_TIMEOUT_SECONDS = 60.0
EXPECTED_CORPUS_SHA256 = "814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de"
RUNTIME_DIRECTORY = API_ROOT.parents[1] / ".runtime" / "phase17b"
_FROZEN_SCENARIO_ID = re.compile(r"^p17b-\d{2}$")


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
        if self.request_starts >= MAX_REQUEST_STARTS:
            raise RuntimeError("frozen corpus request-start ceiling exceeded")
        self.request_starts += 1
        started_at = datetime.now(UTC)
        started = time.monotonic()
        receipt: dict[str, object] = {
            "request_number": self.request_starts,
            "request_started_at": started_at.isoformat(),
            "configured_timeout_seconds": CONFIGURED_TIMEOUT_SECONDS,
            "governor_admission": "admitted",
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
            "retries": 0,
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
        )
    )
    governed = GovernedEvaluationProvider(provider, GroqEvaluationGovernor(time.monotonic, sleeper))
    return await run_with_provider(corpus, digest, output, checkpoint, provider, governed)


async def run_with_provider(
    corpus: FrozenInvestigationCorpus,
    digest: str,
    output: Path,
    checkpoint: Path,
    provider: MeteredProvider,
    governed: GovernedEvaluationProvider,
) -> bool:
    """Dependency-injected offline seam; production paths never call this."""
    results: list[BenchmarkScenarioResult] = []
    provider.persist_receipt = lambda: _checkpoint(checkpoint, provider, tuple(results))
    for scenario in corpus.scenarios:
        remaining = MAX_REQUEST_STARTS - provider.request_starts
        if remaining <= 0:
            raise RuntimeError("frozen corpus request-start ceiling exhausted")
        result = await run_frozen_scenario(
            cast(EvidenceInvestigatorProvider, governed),
            scenario,
            corpus_id=corpus.corpus_id,
            max_requests=min(9, remaining),
        )
        results.append(result)
        _checkpoint(checkpoint, provider, tuple(results))
        if result.provider_failed or result.malformed_output:
            return False
    report = build_benchmark_report(corpus, digest, tuple(results))
    payload = json.loads(sanitized_report_json(report))
    payload["run"] = {
        "provider": "groq",
        "model": MODEL,
        "generated_at": datetime.now(UTC).isoformat(),
        "requests_started": provider.request_starts,
        "responses_received": provider.responses_received,
        "requests_indeterminate": provider.requests_indeterminate,
        "sdk_attempts": provider.request_starts,
        "retries": 0,
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
