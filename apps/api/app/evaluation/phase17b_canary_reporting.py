"""Durable, allowlisted receipts for the evaluation-only Groq canary."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

REPORT_SCHEMA_VERSION = "phase17b-groq-canary-v1"
RUNTIME_REPORT_DIRECTORY = Path(__file__).parents[4] / ".runtime" / "phase17b"

_RUN_STATUSES = frozenset(
    {
        "success",
        "governor_rejected",
        "provider_400",
        "provider_429",
        "provider_5xx",
        "transport_indeterminate",
        "malformed_response",
        "correlation_failed",
        "unexpected_turn",
        "invalid_terminal_schema",
        "internal_failure",
    }
)
_FAILURE_KINDS = frozenset(
    {
        "configuration",
        "access_denied",
        "quota_exhausted",
        "timeout",
        "transient_provider",
        "malformed_response",
        "provider_rejected",
        "unknown_provider",
        "governor_rejected",
        "internal_failure",
    }
)
_ALLOWED_STATUS_CODES = frozenset({400, 401, 403, 429, 500, 501, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class CanaryStateReceipt:
    number: int
    name: str
    outcome: str
    correlation_valid: bool | None = None
    terminal_function: str | None = None
    terminal_schema_valid: bool | None = None
    failure_kind: str | None = None
    status_code: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    quota_metadata: dict[str, int | float | str | None] | None = None


@dataclass(frozen=True, slots=True)
class CanaryTerminalReport:
    schema_version: str
    run_status: str
    model: str
    started_at: str
    ended_at: str
    latency_ms: int
    requests_started: int
    responses_received: int
    requests_indeterminate: int
    sdk_attempts: int
    retries: int
    states: tuple[CanaryStateReceipt, ...]
    tool_execution_count: int = 0


def _safe_status_code(status_code: int | None) -> int | None:
    return status_code if status_code in _ALLOWED_STATUS_CODES else None


def _safe_failure_kind(failure_kind: str | None) -> str | None:
    return failure_kind if failure_kind in _FAILURE_KINDS else None


def _safe_quota(metadata: dict[str, object] | None) -> dict[str, int | float | str | None] | None:
    if metadata is None:
        return None
    allowed = {
        "category",
        "request_limit",
        "request_remaining",
        "token_limit",
        "token_remaining",
        "request_reset_seconds",
        "token_reset_seconds",
        "retry_after_seconds",
    }
    return {
        key: value
        for key, value in metadata.items()
        if key in allowed and isinstance(value, (int, float, str, type(None)))
    }


def state_receipt(
    *,
    number: int,
    name: str,
    outcome: str,
    correlation_valid: bool | None = None,
    terminal_function: str | None = None,
    terminal_schema_valid: bool | None = None,
    failure_kind: str | None = None,
    status_code: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    quota_metadata: dict[str, object] | None = None,
) -> CanaryStateReceipt:
    """Build an explicitly allowlisted state receipt; never accept raw payloads."""
    return CanaryStateReceipt(
        number=number,
        name=name,
        outcome=outcome,
        correlation_valid=correlation_valid,
        terminal_function=terminal_function,
        terminal_schema_valid=terminal_schema_valid,
        failure_kind=_safe_failure_kind(failure_kind),
        status_code=_safe_status_code(status_code),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        quota_metadata=_safe_quota(quota_metadata),
    )


def terminal_report(
    *,
    status: str,
    model: str,
    started_at: datetime,
    states: tuple[CanaryStateReceipt, ...],
    requests_started: int,
    responses_received: int,
    requests_indeterminate: int,
    ended_at: datetime | None = None,
) -> CanaryTerminalReport:
    if status not in _RUN_STATUSES:
        raise ValueError("Unrecognized canary terminal status")
    if min(requests_started, responses_received, requests_indeterminate) < 0:
        raise ValueError("Canary counters cannot be negative")
    if responses_received + requests_indeterminate > requests_started:
        raise ValueError("Canary response counters exceed starts")
    if requests_started > 3 or len(states) > 3:
        raise ValueError("Canary request bound exceeded")
    ended = ended_at or datetime.now(UTC)
    return CanaryTerminalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        run_status=status,
        model=model,
        started_at=started_at.astimezone(UTC).isoformat(),
        ended_at=ended.astimezone(UTC).isoformat(),
        latency_ms=max(0, int((ended - started_at).total_seconds() * 1000)),
        requests_started=requests_started,
        responses_received=responses_received,
        requests_indeterminate=requests_indeterminate,
        sdk_attempts=requests_started,
        retries=0,
        states=states,
    )


def write_report_once(destination: Path, report: CanaryTerminalReport) -> None:
    root = RUNTIME_REPORT_DIRECTORY.resolve()
    target = destination.resolve()
    if target.parent != root or target.suffix != ".json":
        raise ValueError(
            "Canary reports must be new JSON files in the ignored Phase 17B runtime directory"
        )
    if target.exists():
        raise FileExistsError("Canary report destination already exists")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{target.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(asdict(report), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            raise FileExistsError("Canary report destination already exists")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
