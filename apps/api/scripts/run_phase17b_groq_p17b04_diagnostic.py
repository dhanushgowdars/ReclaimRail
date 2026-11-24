"""Owner-gated, evaluation-only Groq diagnostic for frozen scenario p17b-04."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.evaluation.phase17b_benchmark import (  # noqa: E402
    BenchmarkScenarioResult,
    FrozenInvestigationScenario,
    load_frozen_corpus,
    run_frozen_scenario,
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
from scripts.run_phase17b_groq_benchmark import (  # noqa: E402
    MeteredProvider,
    _atomic_json,
)

MODEL = "openai/gpt-oss-120b"
PROVIDER = "groq"
SCENARIO_ID = "p17b-04"
EXPECTED_CORPUS_ID = "reclaimrail-phase17b-v2"
EXPECTED_CORPUS_SHA256 = "814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de"
STARTING_BUDGET_ACKNOWLEDGEMENT = "44/150"
LIVE_ACKNOWLEDGEMENT = "OWNER_APPROVED_PHASE17B_P17B04_DIAGNOSTIC_LIVE"
MAX_REQUEST_STARTS = 3
AUTHORIZED_LIVE_MAX_REQUEST_STARTS = 6
CONFIGURED_TIMEOUT_SECONDS = 60.0
CORPUS_PATH = API_ROOT / "benchmarks" / "phase17b" / "corpus-v2.json"
CHECKSUM_PATH = API_ROOT / "benchmarks" / "phase17b" / "corpus-v2.sha256"
RUNTIME_DIRECTORY = API_ROOT.parents[1] / ".runtime" / "phase17b"
OUTPUT_PREFIX = "groq-p17b-04-diagnostic-"
RUN_LOCK_NAME = ".groq-p17b-04-diagnostic.lock"
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KEY = re.compile(r"(?i)\b(?:sk|rk|key|token|secret)[-_A-Za-z0-9]*\s*[:=]\s*[^\s,;]+")
_HEADER = re.compile(
    r"(?i)\b(?:authorization|x-api-key|api-key|cookie|set-cookie)\s*[:=]\s*[^\s,;]+"
)


class DiagnosticStartCeilingError(RuntimeError):
    """Raised before transport if the diagnostic tries to start a fourth request."""


class DiagnosticAlreadyRunningError(RuntimeError):
    """Raised before credentials or transport when another diagnostic holds the lease."""


def _scrub_text(value: object, limit: int = 300) -> str:
    text = str(value)
    text = _BEARER.sub("[REDACTED_BEARER]", text)
    text = _KEY.sub(
        lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=[REDACTED]", text
    )
    text = _HEADER.sub("[REDACTED_HEADER]", text)
    return text[:limit]


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
        value = source.get(key)
        if isinstance(value, str):
            safe[key] = _scrub_text(value, 256)
    if "arguments" in source:
        encoded = json.dumps(
            source["arguments"], sort_keys=True, separators=(",", ":"), default=str
        )
        safe["arguments"] = _scrub_text(encoded, 500)
    message = source.get("scrubbed_error_message")
    if message is not None:
        safe["scrubbed_error_message"] = _scrub_text(message, 300)
    if error is not None and isinstance(error, EvidenceInvestigatorProviderError):
        if error.status_code is not None:
            safe["http_status"] = error.status_code
        safe["provider_error_type"] = error.kind.value
        if error.reason_code is not None:
            safe["provider_error_code"] = error.reason_code.value
        safe.setdefault("scrubbed_error_message", "Groq evidence investigation failed safely")
        safe.setdefault("turn_type", "provider_error")
    return safe


class DiagnosticMeteredProvider(MeteredProvider):
    """Meter plus sanitized, synthetic-diagnostic-only provider receipt details."""

    def _capture_diagnostics(self, error: BaseException | None = None) -> None:
        if self.receipts:
            details = getattr(self.provider, "last_diagnostic_details", None)
            safe = _safe_diagnostic_details(details, error)
            if safe:
                self.receipts[-1]["diagnostic"] = safe

    async def next_turn(self, request: dict[str, object]):  # type: ignore[no-untyped-def]
        try:
            response = await super().next_turn(request)
        except BaseException as error:
            self._capture_diagnostics(error)
            self._persist()
            raise
        self._capture_diagnostics()
        self._persist()
        return response


@dataclass(slots=True)
class ThreeStartProvider:
    """Independent transport-side cap around the existing sanitized meter."""

    provider: MeteredProvider
    maximum_starts: int = MAX_REQUEST_STARTS

    async def next_turn(self, request: dict[str, object]) -> object:
        if self.provider.request_starts >= self.maximum_starts:
            raise DiagnosticStartCeilingError("p17b-04 diagnostic request ceiling reached")
        return await self.provider.next_turn(request)


def _load_locked_scenario() -> tuple[FrozenInvestigationScenario, str]:
    corpus, digest = load_frozen_corpus(CORPUS_PATH, CHECKSUM_PATH)
    if corpus.corpus_id != EXPECTED_CORPUS_ID or digest != EXPECTED_CORPUS_SHA256:
        raise ValueError("diagnostic requires the locked Phase 17B corpus-v2")
    matches = tuple(item for item in corpus.scenarios if item.scenario_id == SCENARIO_ID)
    if len(matches) != 1:
        raise ValueError("diagnostic requires exactly one frozen p17b-04 scenario")
    return matches[0], digest


def _validate_destination(path: Path) -> tuple[Path, Path]:
    output = path.resolve()
    runtime = RUNTIME_DIRECTORY.resolve()
    if (
        output.parent != runtime
        or output.suffix != ".json"
        or not output.name.startswith(OUTPUT_PREFIX)
        or output.name.startswith(".")
    ):
        raise ValueError(
            "diagnostic output must be a named p17b-04 JSON artifact in .runtime/phase17b"
        )
    checkpoint = output.with_name(f".{output.stem}.checkpoint.json")
    if output.exists() or checkpoint.exists():
        raise FileExistsError("diagnostic output and checkpoint paths must both be new")
    return output, checkpoint


@contextmanager
def _exclusive_run() -> Iterator[None]:
    """Hold one process-visible diagnostic lease; a stale lease fails closed."""
    runtime = RUNTIME_DIRECTORY.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    lock = runtime / RUN_LOCK_NAME
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write("p17b-04 diagnostic active\n")
    except FileExistsError:
        raise DiagnosticAlreadyRunningError(
            "another p17b-04 diagnostic is active or requires operator inspection"
        ) from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _diagnostic_status(result: BenchmarkScenarioResult) -> str:
    if result.terminal_reason == "terminal_turn":
        if not result.citations_valid or not result.failed_safe:
            return "unsafe_terminal_response"
        return "terminal_response"
    if result.terminal_reason == "request_budget_exhausted":
        return "incomplete_request_ceiling"
    if result.terminal_reason == "invalid_or_repeated_tool_request":
        return "unsafe_turn"
    if result.malformed_output:
        return "malformed_output"
    if result.provider_failed:
        return "provider_or_governor_failure"
    return "failed_safe"


def _safe_result(result: BenchmarkScenarioResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    payload: dict[str, object] = {
        "diagnostic_status": _diagnostic_status(result),
        "scenario_id": SCENARIO_ID,
        "request_count": result.request_count,
        "provider_failed": result.provider_failed,
        "malformed_output": result.malformed_output,
        "failed_safe": result.failed_safe,
        "citations_valid": result.citations_valid,
    }
    if result.provider_status_code is not None:
        payload["provider_status_code"] = result.provider_status_code
    if result.provider_reason_code is not None:
        payload["provider_reason_code"] = result.provider_reason_code
    if result.rate_limit_metadata is not None:
        payload["rate_limit_metadata"] = result.rate_limit_metadata
    return payload


def _artifact(
    provider: MeteredProvider,
    digest: str,
    result: BenchmarkScenarioResult | None,
    max_request_starts: int = MAX_REQUEST_STARTS,
) -> dict[str, object]:
    return {
        "schema_version": "phase17b-groq-p17b04-diagnostic-v1",
        "scope": "single_scenario_diagnostic",
        "provider": PROVIDER,
        "model": MODEL,
        "corpus_id": EXPECTED_CORPUS_ID,
        "corpus_sha256": digest,
        "scenario_id": SCENARIO_ID,
        "starting_budget_acknowledgement": STARTING_BUDGET_ACKNOWLEDGEMENT,
        "maximum_request_starts": max_request_starts,
        "requests_started": provider.request_starts,
        "responses_received": provider.responses_received,
        "requests_indeterminate": provider.requests_indeterminate,
        "sdk_attempts": provider.request_starts,
        "retries": 0,
        "failover": False,
        "request_receipts": provider.receipts,
        "result": _safe_result(result),
        "corpus_verdict": "not_evaluated",
        "model_selection": "not_evaluated",
    }


def _checkpoint(
    path: Path,
    provider: MeteredProvider,
    digest: str,
    result: BenchmarkScenarioResult | None,
    max_request_starts: int = MAX_REQUEST_STARTS,
) -> None:
    _atomic_json(path, _artifact(provider, digest, result, max_request_starts), overwrite=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one separately authorized Groq diagnostic for frozen p17b-04."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-starting-budget", required=True)
    parser.add_argument("--acknowledge-live-groq", required=True)
    return parser.parse_args(argv)


def _preflight(args: argparse.Namespace) -> tuple[Path, Path, FrozenInvestigationScenario, str]:
    if args.acknowledge_starting_budget != STARTING_BUDGET_ACKNOWLEDGEMENT:
        raise ValueError("starting budget acknowledgement must be exactly 41/150")
    if args.acknowledge_live_groq != LIVE_ACKNOWLEDGEMENT:
        raise ValueError("live Groq acknowledgement does not match the diagnostic token")
    output, checkpoint = _validate_destination(args.output)
    scenario, digest = _load_locked_scenario()
    return output, checkpoint, scenario, digest


async def run_with_provider(
    scenario: FrozenInvestigationScenario,
    digest: str,
    output: Path,
    checkpoint: Path,
    provider: MeteredProvider,
    governed: GovernedEvaluationProvider,
    max_request_starts: int = MAX_REQUEST_STARTS,
) -> bool:
    """Dependency-injected offline seam; it never evaluates corpus/model quality."""
    provider.persist_receipt = lambda: _checkpoint(
        checkpoint, provider, digest, None, max_request_starts
    )
    result = await run_frozen_scenario(
        cast(EvidenceInvestigatorProvider, governed),
        scenario,
        corpus_id=EXPECTED_CORPUS_ID,
        max_requests=max_request_starts,
    )
    _checkpoint(checkpoint, provider, digest, result, max_request_starts)
    _atomic_json(output, _artifact(provider, digest, result, max_request_starts), overwrite=False)
    return _diagnostic_status(result) == "terminal_response"


async def run(args: argparse.Namespace) -> bool:
    output, checkpoint, scenario, digest = _preflight(args)
    with _exclusive_run():
        # Close the preflight-to-first-checkpoint race after acquiring the global lease.
        output, checkpoint = _validate_destination(args.output)
        settings = get_settings()
        key = settings.groq_api_key.get_secret_value().strip() if settings.groq_api_key else ""
        if not key:
            raise ValueError("Groq API access is not configured")

        async def sleeper(seconds: float) -> None:
            await asyncio.sleep(seconds)

        metered = DiagnosticMeteredProvider(
            GroqEvidenceInvestigator(
                api_key=key,
                model_name=MODEL,
                max_output_tokens=512,
                request_timeout_seconds=CONFIGURED_TIMEOUT_SECONDS,
            )
        )
        # This is the sole explicitly authorized live-run expansion; offline seams default to 3.
        capped_limit = AUTHORIZED_LIVE_MAX_REQUEST_STARTS
        capped = ThreeStartProvider(metered, maximum_starts=capped_limit)
        governed = GovernedEvaluationProvider(
            capped,
            GroqEvaluationGovernor(time.monotonic, sleeper),
        )
        return await run_with_provider(
            scenario,
            digest,
            output,
            checkpoint,
            metered,
            governed,
            max_request_starts=capped_limit,
        )


def main() -> None:
    raise SystemExit(0 if asyncio.run(run(parse_args())) else 1)


if __name__ == "__main__":
    main()
