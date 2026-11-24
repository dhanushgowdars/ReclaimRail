"""Explicitly invoked, evaluation-only controlled-synthetic Groq canary command."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.core.config import get_settings  # noqa: E402 - direct-script path bootstrap above
from app.domain.investigation import InvestigatorProviderResponse  # noqa: E402
from app.evaluation.phase17b_canary_reporting import (  # noqa: E402
    RUNTIME_REPORT_DIRECTORY,
    CanaryStateReceipt,
    CanaryTerminalReport,
    state_receipt,
    terminal_report,
    write_report_once,
)
from app.evaluation.phase17b_groq_canary import run_groq_canary  # noqa: E402
from app.evaluation.phase17b_groq_governor import (  # noqa: E402
    GovernedEvaluationProvider,
    GovernorStoppedError,
    GroqEvaluationGovernor,
)
from app.integrations.groq.evidence_investigator import GroqEvidenceInvestigator  # noqa: E402
from app.integrations.investigator import EvidenceInvestigatorProviderError  # noqa: E402

MODEL = "openai/gpt-oss-120b"
_STATE_NAMES = ("get_truth_snapshot", "get_verified_webhooks", "terminal")


class TurnProvider(Protocol):
    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse: ...


@dataclass(slots=True)
class _MeteredProvider:
    provider: TurnProvider
    requests_started: int = 0
    responses_received: int = 0
    requests_indeterminate: int = 0
    states: list[CanaryStateReceipt] = field(default_factory=list)

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        number = self.requests_started + 1
        if number > 3:
            raise RuntimeError("canary request bound exceeded")
        self.requests_started += 1
        name = _STATE_NAMES[number - 1]
        try:
            response = await self.provider.next_turn(request)
        except EvidenceInvestigatorProviderError as error:
            if error.status_code is not None or error.kind.value == "malformed_response":
                self.responses_received += 1
            else:
                self.requests_indeterminate += 1
            raise
        except Exception:
            self.requests_indeterminate += 1
            raise
        self.responses_received += 1
        typed = cast(InvestigatorProviderResponse, response)
        action = getattr(typed.turn, "action", None)
        self.states.append(
            state_receipt(
                number=number,
                name=name,
                outcome="response_received",
                correlation_valid=True if number < 3 else None,
                terminal_function=action.value if number == 3 and action is not None else None,
                terminal_schema_valid=True if number == 3 else None,
                input_tokens=typed.input_token_count,
                output_tokens=typed.output_token_count,
                quota_metadata=typed.quota_metadata,
            )
        )
        return typed


def validate_output(path: Path) -> None:
    if path.resolve().parent != RUNTIME_REPORT_DIRECTORY.resolve() or path.exists():
        raise ValueError("Canary output must be a new ignored Phase 17B runtime report")


def _failure_status(error: BaseException) -> tuple[str, str | None, int | None]:
    if isinstance(error, GovernorStoppedError):
        return "governor_rejected", "governor_rejected", None
    if not isinstance(error, EvidenceInvestigatorProviderError):
        return "internal_failure", "internal_failure", None
    status = error.status_code
    if status == 400:
        return "provider_400", error.kind.value, status
    if status == 429:
        return "provider_429", error.kind.value, status
    if status is not None and 500 <= status <= 599:
        return "provider_5xx", error.kind.value, status
    if error.kind.value in {"timeout", "transient_provider"}:
        return "transport_indeterminate", error.kind.value, status
    if error.kind.value == "malformed_response":
        return "malformed_response", error.kind.value, status
    return "unexpected_turn", error.kind.value, status


async def run_and_write_report(
    *,
    provider: TurnProvider,
    governor: GroqEvaluationGovernor,
    destination: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CanaryTerminalReport:
    """Run the existing canary and persist one sanitized terminal receipt."""
    validate_output(destination)
    started = now()
    metered = _MeteredProvider(provider)
    status = "success"
    try:
        result = await run_groq_canary(
            GovernedEvaluationProvider(metered, governor, max_attempts=1)
        )
        if result.request_count != 3 or result.tool_execution_count != 0:
            raise RuntimeError("canary result violated request or execution bounds")
    except BaseException as error:
        status, failure_kind, status_code = _failure_status(error)
        number = metered.requests_started or 1
        if not metered.states or metered.states[-1].number != number:
            metered.states.append(
                state_receipt(
                    number=number,
                    name=_STATE_NAMES[number - 1],
                    outcome="failed_closed",
                    failure_kind=failure_kind,
                    status_code=status_code,
                )
            )
    report = terminal_report(
        status=status,
        model=MODEL,
        started_at=started,
        states=tuple(metered.states),
        requests_started=metered.requests_started,
        responses_received=metered.responses_received,
        requests_indeterminate=metered.requests_indeterminate,
        ended_at=now(),
    )
    write_report_once(destination, report)
    return report


def _live_provider(key: str) -> GroqEvidenceInvestigator:
    return GroqEvidenceInvestigator(
        api_key=key,
        model_name=MODEL,
        max_output_tokens=512,
        request_timeout_seconds=60.0,
    )


def canary_exit_code(report: CanaryTerminalReport) -> int:
    """A durable failure receipt is still a failing command result."""
    return 0 if report.run_status == "success" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Owner-gated Phase 17B Groq synthetic canary")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-approved-live-run", action="store_true")
    args = parser.parse_args()
    if not args.owner_approved_live_run:
        raise SystemExit("Refusing live provider invocation without --owner-approved-live-run")
    validate_output(args.output)
    started = datetime.now(UTC)
    settings = get_settings()
    key = settings.groq_api_key.get_secret_value().strip() if settings.groq_api_key else ""
    if not key:
        write_report_once(
            args.output,
            terminal_report(
                status="internal_failure",
                model=MODEL,
                started_at=started,
                states=(
                    state_receipt(
                        number=1,
                        name="get_truth_snapshot",
                        outcome="failed_closed",
                        failure_kind="configuration",
                    ),
                ),
                requests_started=0,
                responses_received=0,
                requests_indeterminate=0,
            ),
        )
        raise SystemExit("RECLAIMRAIL_GROQ_API_KEY is not configured")

    async def sleeper(seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def execute() -> CanaryTerminalReport:
        return await run_and_write_report(
            provider=_live_provider(key),
            governor=GroqEvaluationGovernor(clock=time.monotonic, sleeper=sleeper),
            destination=args.output,
        )

    raise SystemExit(canary_exit_code(asyncio.run(execute())))


if __name__ == "__main__":
    main()
