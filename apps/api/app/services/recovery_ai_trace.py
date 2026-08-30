"""PII-safe projection of persisted recovery-planner evidence for reviewers."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RecoveryAiTrace:
    """Explain what the planner concluded without exposing prompt inputs or contacts."""

    root_cause_category: str | None
    recoverability_assessment: str | None
    confidence: float | None
    recommended_action: str | None
    evidence_references: tuple[str, ...]
    evidence_codes: tuple[str, ...]
    evidence_tool_names: tuple[str, ...]
    input_token_count: int | None
    output_token_count: int | None
    fallback_used: bool | None
    fallback_reason: str | None


def build_recovery_ai_trace(evidence: object) -> RecoveryAiTrace:
    """Return a bounded, display-safe trace from an agent run's JSON evidence."""
    payload = evidence if isinstance(evidence, dict) else {}
    planner = _mapping(payload.get("planner"))
    analysis = _mapping(payload.get("bounded_ai_analysis"))
    tools = _mapping(payload.get("bounded_ai_evidence_tools"))

    confidence = analysis.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = None

    return RecoveryAiTrace(
        root_cause_category=_string(analysis.get("root_cause_category")),
        recoverability_assessment=_string(analysis.get("recoverability_assessment")),
        confidence=float(confidence) if confidence is not None else None,
        recommended_action=_string(analysis.get("allowed_action_recommendation")),
        evidence_references=_strings(analysis.get("evidence_references")),
        evidence_codes=_strings(payload.get("evidence_codes")),
        evidence_tool_names=tuple(sorted(key for key in tools if isinstance(key, str))),
        input_token_count=_non_negative_int(planner.get("input_token_count")),
        output_token_count=_non_negative_int(planner.get("output_token_count")),
        fallback_used=_bool_or_none(planner.get("fallback_used", payload.get("fallback_used"))),
        fallback_reason=_string(planner.get("fallback_reason", payload.get("fallback_reason"))),
    )


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _non_negative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
