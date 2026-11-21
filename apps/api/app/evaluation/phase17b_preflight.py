"""Bounded, secret-safe Gemini access preflight for Phase 17B."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.integrations.gemini.evidence_investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    GeminiModelAccessEvidence,
    GeminiModelAccessProvider,
)
from app.services.recovery_investigation_tools import public_tool_catalog

LIVE_PREFLIGHT_ACKNOWLEDGEMENT = (
    "OWNER_APPROVED_PHASE17B_MODEL_DISCOVERY_AND_INTERACTIONS_PREFLIGHT"
)
PREFLIGHT_CASE_ID = "00000000-0000-4000-8000-000000000017"
PREFLIGHT_TOOL_NAME = "get_truth_snapshot"
PREFLIGHT_MAX_OUTPUT_TOKENS = 512
PREFLIGHT_REQUEST_TIMEOUT_SECONDS = 30.0
PREFLIGHT_REQUEST_BUDGET = 2
SUPPORTED_PREFLIGHT_CANDIDATES = {
    "gemini-3.8-flash": "low",
    "gemini-3.6-flash": "minimal",
}
_MODEL_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class Phase17BPreflightCandidate:
    model: str
    thinking_level: str


@dataclass(frozen=True, slots=True)
class Phase17BPreflightReport:
    status: Literal["passed", "failed_safe"]
    requested_model: str
    thinking_level: str
    request_count: int
    api_route: Literal["generate_content"]
    evidence_mode: Literal["controlled_synthetic"]
    latency_ms: float
    adapter_model_name: str | None
    provider_model_version: str | None
    input_token_count: int | None
    output_token_count: int | None
    schema_valid: bool
    tool_contract_valid: bool
    failure_kind: str | None
    provider_status_code: int | None
    provider_status: str | None
    provider_reason_code: str | None
    model_discovery_valid: bool
    discovered_model_version: str | None
    terminal_reason: str


def validate_preflight_authorization(
    *,
    acknowledgement: str,
    request_budget: int,
    model: str,
    thinking_level: str,
) -> Phase17BPreflightCandidate:
    if acknowledgement != LIVE_PREFLIGHT_ACKNOWLEDGEMENT:
        raise ValueError("Live Gemini preflight acknowledgement does not match")
    if request_budget != PREFLIGHT_REQUEST_BUDGET:
        raise ValueError(
            f"Phase 17B preflight request budget must be exactly {PREFLIGHT_REQUEST_BUDGET}",
        )
    expected_thinking = SUPPORTED_PREFLIGHT_CANDIDATES.get(model)
    if expected_thinking is None:
        raise ValueError("Model is not in the Phase 17B preflight allowlist")
    if thinking_level != expected_thinking:
        raise ValueError(
            f"Phase 17B requires thinking level {expected_thinking!r} for model {model!r}",
        )
    return Phase17BPreflightCandidate(model=model, thinking_level=thinking_level)


def build_preflight_request() -> dict[str, object]:
    """Return a synthetic request that selects a tool but never executes it."""

    tools = tuple(tool for tool in public_tool_catalog() if tool.get("name") == PREFLIGHT_TOOL_NAME)
    if len(tools) != 1 or tools[0].get("read_only") is not True:
        raise RuntimeError("Phase 17B preflight tool must exist and remain read-only")
    return {
        "preflight": {
            "id": "reclaimrail-phase17b-model-access-v1",
            "evidence_mode": "controlled_synthetic",
            "purpose": "verify access, structured output, and read-only tool selection",
        },
        "objective": (
            "For this controlled synthetic case, request the read-only truth snapshot "
            "tool exactly once. Do not conclude, abstain, or take any action."
        ),
        "case": {
            "case_id": PREFLIGHT_CASE_ID,
            "provenance": "controlled_synthetic",
        },
        "tools": tools,
        "observations": [],
        "budgets_remaining": {"tool_calls": 1, "model_requests": 1},
        "response_contract": (f"call {PREFLIGHT_TOOL_NAME} with only case_id={PREFLIGHT_CASE_ID}"),
    }


def _parse_turn(response: InvestigatorProviderResponse) -> InvestigatorTurn:
    if isinstance(response.turn, InvestigatorTurn):
        return response.turn
    if isinstance(response.turn, str):
        return InvestigatorTurn.model_validate_json(response.turn)
    return InvestigatorTurn.model_validate(response.turn)


def _report(
    candidate: Phase17BPreflightCandidate,
    *,
    started_ns: int,
    monotonic_ns: Callable[[], int],
    request_count: int,
    status: Literal["passed", "failed_safe"] = "failed_safe",
    response: InvestigatorProviderResponse | None = None,
    schema_valid: bool = False,
    tool_contract_valid: bool = False,
    failure_kind: str | None = None,
    provider_status_code: int | None = None,
    provider_status: str | None = None,
    provider_reason_code: str | None = None,
    model_access: GeminiModelAccessEvidence | None = None,
    model_discovery_valid: bool = False,
    terminal_reason: str,
) -> Phase17BPreflightReport:
    elapsed_ns = max(0, monotonic_ns() - started_ns)
    adapter_model_name = (
        response.model_name
        if response is not None and response.model_name == candidate.model
        else None
    )
    provider_model_version = (
        response.model_version
        if response is not None
        and response.model_version is not None
        and _MODEL_VERSION_PATTERN.fullmatch(response.model_version)
        else None
    )
    return Phase17BPreflightReport(
        status=status,
        requested_model=candidate.model,
        thinking_level=candidate.thinking_level,
        request_count=request_count,
        api_route="generate_content",
        evidence_mode="controlled_synthetic",
        latency_ms=round(elapsed_ns / 1_000_000, 3),
        adapter_model_name=adapter_model_name,
        provider_model_version=provider_model_version,
        input_token_count=response.input_token_count if response is not None else None,
        output_token_count=response.output_token_count if response is not None else None,
        schema_valid=schema_valid,
        tool_contract_valid=tool_contract_valid,
        failure_kind=failure_kind,
        provider_status_code=provider_status_code,
        provider_status=provider_status,
        provider_reason_code=provider_reason_code,
        model_discovery_valid=model_discovery_valid,
        discovered_model_version=(
            model_access.model_version
            if model_access is not None
            and model_access.model_version is not None
            and _MODEL_VERSION_PATTERN.fullmatch(model_access.model_version)
            else None
        ),
        terminal_reason=terminal_reason,
    )


async def run_phase17b_preflight(
    provider: GeminiModelAccessProvider,
    candidate: Phase17BPreflightCandidate,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> Phase17BPreflightReport:
    """Make one discovery plus one interaction request; never execute the selected tool."""

    started_ns = monotonic_ns()
    request_count = 1
    try:
        model_access = await provider.discover_model_access()
    except EvidenceInvestigatorProviderError as error:
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            failure_kind=error.kind.value,
            provider_status_code=error.status_code,
            provider_status=error.provider_status,
            provider_reason_code=error.reason_code.value if error.reason_code else None,
            terminal_reason=f"model_discovery_{error.kind.value}",
        )
    except Exception:  # noqa: BLE001 - untrusted provider boundary is sanitized
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            failure_kind=EvidenceInvestigatorFailureKind.UNKNOWN_PROVIDER.value,
            terminal_reason="model_discovery_unknown_provider",
        )
    model_discovery_valid = (
        model_access.model_name == candidate.model
        and (
            model_access.output_token_limit is None
            or model_access.output_token_limit >= PREFLIGHT_MAX_OUTPUT_TOKENS
        )
        and model_access.thinking_supported is not False
    )
    if not model_discovery_valid:
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            model_access=model_access,
            terminal_reason="model_discovery_contract_mismatch",
        )

    request_count += 1
    try:
        response = await provider.next_turn(build_preflight_request())
    except EvidenceInvestigatorProviderError as error:
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            failure_kind=error.kind.value,
            provider_status_code=error.status_code,
            provider_status=error.provider_status,
            provider_reason_code=error.reason_code.value if error.reason_code else None,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason=f"provider_{error.kind.value}",
        )
    except Exception:  # noqa: BLE001 - untrusted provider boundary is sanitized
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            failure_kind=EvidenceInvestigatorFailureKind.UNKNOWN_PROVIDER.value,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason="provider_unknown_provider",
        )

    if response.model_name != candidate.model:
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            response=response,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason="adapter_model_mismatch",
        )
    if not response.model_version or not _MODEL_VERSION_PATTERN.fullmatch(response.model_version):
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            response=response,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason="provider_model_version_missing_or_invalid",
        )
    if (
        response.input_token_count is None
        or response.input_token_count <= 0
        or response.output_token_count is None
        or response.output_token_count <= 0
    ):
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            response=response,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason="usage_metadata_incomplete",
        )
    try:
        turn = _parse_turn(response)
    except Exception:  # noqa: BLE001 - strict schema boundary
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            response=response,
            failure_kind=EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE.value,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason="malformed_model_output",
        )

    schema_valid = True
    tool_contract_valid = (
        turn.action is InvestigationTurnAction.CALL_TOOL
        and turn.tool_name == PREFLIGHT_TOOL_NAME
        and turn.tool_arguments == {"case_id": PREFLIGHT_CASE_ID}
    )
    if not tool_contract_valid:
        return _report(
            candidate,
            started_ns=started_ns,
            monotonic_ns=monotonic_ns,
            request_count=request_count,
            response=response,
            schema_valid=schema_valid,
            model_access=model_access,
            model_discovery_valid=True,
            terminal_reason="tool_contract_mismatch",
        )
    return _report(
        candidate,
        started_ns=started_ns,
        monotonic_ns=monotonic_ns,
        request_count=request_count,
        status="passed",
        response=response,
        schema_valid=schema_valid,
        tool_contract_valid=True,
        model_access=model_access,
        model_discovery_valid=True,
        terminal_reason="preflight_passed",
    )


def sanitized_preflight_report_json(report: Phase17BPreflightReport) -> str:
    """Serialize only bounded metadata; prompts, responses and credentials are excluded."""

    return json.dumps(asdict(report), indent=2, sort_keys=True)
