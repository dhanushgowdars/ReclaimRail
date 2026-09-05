"""PII-safe projection of persisted recovery-planner evidence for reviewers."""

from dataclasses import dataclass
from typing import Any

from app.services.money_display import format_minor_amount


@dataclass(frozen=True, slots=True)
class RecoveryAiEvidenceCitation:
    """A display-safe fact from an evidence surface cited by the planner."""

    reference: str
    label: str
    observations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryAiReasoningItem:
    evidence_references: tuple[str, ...]
    interpretation: str
    action_impact: str


@dataclass(frozen=True, slots=True)
class RecoveryAiAlternative:
    action_type: str
    disposition: str
    reason: str
    evidence_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryAiTrace:
    """Explain what the planner concluded without exposing prompt inputs or contacts."""

    root_cause_category: str | None
    recoverability_assessment: str | None
    recommended_action: str | None
    evidence_references: tuple[str, ...]
    evidence_citations: tuple[RecoveryAiEvidenceCitation, ...]
    evidence_codes: tuple[str, ...]
    evidence_tool_names: tuple[str, ...]
    input_token_count: int | None
    output_token_count: int | None
    fallback_used: bool | None
    fallback_reason: str | None
    operator_explanation: str | None = None
    reasoning_items: tuple[RecoveryAiReasoningItem, ...] = ()
    alternatives_considered: tuple[RecoveryAiAlternative, ...] = ()
    known_uncertainties: tuple[str, ...] = ()


def build_recovery_ai_trace(evidence: object) -> RecoveryAiTrace:
    """Return a bounded, display-safe trace from an agent run's JSON evidence."""
    payload = evidence if isinstance(evidence, dict) else {}
    planner = _mapping(payload.get("planner"))
    analysis = _mapping(payload.get("bounded_ai_analysis"))
    tools = _mapping(payload.get("bounded_ai_evidence_tools"))

    evidence_references = _strings(analysis.get("evidence_references"))

    return RecoveryAiTrace(
        root_cause_category=_string(analysis.get("root_cause_category")),
        recoverability_assessment=_string(analysis.get("recoverability_assessment")),
        recommended_action=_string(analysis.get("allowed_action_recommendation")),
        evidence_references=evidence_references,
        evidence_citations=_build_evidence_citations(evidence_references, tools),
        evidence_codes=_strings(payload.get("evidence_codes")),
        evidence_tool_names=tuple(sorted(key for key in tools if isinstance(key, str))),
        input_token_count=_non_negative_int(planner.get("input_token_count")),
        output_token_count=_non_negative_int(planner.get("output_token_count")),
        fallback_used=_bool_or_none(planner.get("fallback_used", payload.get("fallback_used"))),
        fallback_reason=_string(planner.get("fallback_reason", payload.get("fallback_reason"))),
        operator_explanation=_display_text(analysis.get("operator_explanation"), tools),
        reasoning_items=_reasoning_items(
            analysis.get("reasoning_items"), evidence_references, tools
        ),
        alternatives_considered=_alternatives(
            analysis.get("alternatives_considered"), evidence_references, tools
        ),
        known_uncertainties=tuple(
            text
            for item in _strings(analysis.get("known_uncertainties"))
            if (text := _display_text(item, tools)) is not None
        ),
    )


def display_recovery_ai_text(value: object, evidence: object) -> str | None:
    """Convert persisted planner minor-unit values in operator-facing prose."""
    payload = evidence if isinstance(evidence, dict) else {}
    return _display_text(value, _mapping(payload.get("bounded_ai_evidence_tools")))


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


def _reasoning_items(
    value: object,
    evidence_references: tuple[str, ...],
    tools: dict[str, Any],
) -> tuple[RecoveryAiReasoningItem, ...]:
    if not isinstance(value, list):
        return ()
    allowed = set(evidence_references)
    items: list[RecoveryAiReasoningItem] = []
    for item in value:
        payload = _mapping(item)
        references = _strings(payload.get("evidence_references"))
        interpretation = _display_text(payload.get("interpretation"), tools)
        action_impact = _display_text(payload.get("action_impact"), tools)
        if (
            references
            and interpretation is not None
            and action_impact is not None
            and set(references).issubset(allowed)
        ):
            items.append(
                RecoveryAiReasoningItem(
                    evidence_references=references,
                    interpretation=interpretation,
                    action_impact=action_impact,
                ),
            )
    return tuple(items)


def _alternatives(
    value: object,
    evidence_references: tuple[str, ...],
    tools: dict[str, Any],
) -> tuple[RecoveryAiAlternative, ...]:
    if not isinstance(value, list):
        return ()
    allowed = set(evidence_references)
    alternatives: list[RecoveryAiAlternative] = []
    for item in value:
        payload = _mapping(item)
        action_type = _string(payload.get("action_type"))
        disposition = _string(payload.get("disposition"))
        reason = _display_text(payload.get("reason"), tools)
        references = _strings(payload.get("evidence_references"))
        if (
            action_type is not None
            and disposition in {"not_selected", "not_applicable"}
            and reason is not None
            and references
            and set(references).issubset(allowed)
        ):
            alternatives.append(
                RecoveryAiAlternative(
                    action_type=action_type,
                    disposition=disposition,
                    reason=reason,
                    evidence_references=references,
                ),
            )
    return tuple(alternatives)


def _build_evidence_citations(
    references: tuple[str, ...],
    tools: dict[str, Any],
) -> tuple[RecoveryAiEvidenceCitation, ...]:
    """Project only persisted, non-PII planner evidence for the reviewer."""

    citations: list[RecoveryAiEvidenceCitation] = []
    for reference in references:
        payload = _mapping(tools.get(reference))
        citation = _citation_for(reference, payload)
        if citation is not None:
            citations.append(citation)
    return tuple(citations)


def _citation_for(
    reference: str,
    payload: dict[str, Any],
) -> RecoveryAiEvidenceCitation | None:
    if reference == "payment_state_snapshot":
        return RecoveryAiEvidenceCitation(
            reference=reference,
            label="Recorded payment state",
            observations=tuple(
                value
                for value in (
                    _observation("State", payload.get("state")),
                    _money_observation(
                        "Amount", payload.get("amount_minor"), payload.get("currency")
                    ),
                    _observation("Currency", payload.get("currency")),
                    _observation("Method", payload.get("payment_method")),
                    _boolean_observation(
                        "Late authorization detected",
                        payload.get("late_authorization_detected"),
                    ),
                )
                if value is not None
            ),
        )
    if reference == "attempt_and_recovery_history":
        return RecoveryAiEvidenceCitation(
            reference=reference,
            label="Attempt and recovery history",
            observations=tuple(
                value
                for value in (
                    _observation("Recovery attempts", payload.get("recovery_attempt_count")),
                    _observation("Failure count", payload.get("failure_count")),
                    _boolean_observation("Active payment link", payload.get("active_payment_link")),
                )
                if value is not None
            ),
        )
    if reference == "payment_rail_incident_context":
        return RecoveryAiEvidenceCitation(
            reference=reference,
            label="Payment-rail incident context",
            observations=(
                _observation("Active incident severity", payload.get("active_incident_severity"))
                or "No active incident recorded",
            ),
        )
    if reference == "merchant_recovery_policy":
        return RecoveryAiEvidenceCitation(
            reference=reference,
            label="Merchant recovery policy",
            observations=tuple(
                value
                for value in (
                    _boolean_observation(
                        "Customer contact allowed",
                        payload.get("customer_contact_allowed"),
                    ),
                    _observation("Approved channels", payload.get("approved_channels")),
                    _observation("Maximum attempts", payload.get("maximum_recovery_attempts")),
                    _money_observation(
                        "Automatic amount limit",
                        payload.get("automatic_amount_limit_minor"),
                        "INR",
                    ),
                )
                if value is not None
            ),
        )
    return None


def _observation(label: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        values = [item for item in value if isinstance(item, str) and item]
        return f"{label}: {', '.join(values) if values else 'none'}"
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return f"{label}: {value}"
    return None


def _boolean_observation(label: str, value: object) -> str | None:
    return f"{label}: {'yes' if value else 'no'}" if isinstance(value, bool) else None


def _money_observation(label: str, amount: object, currency: object) -> str | None:
    if not isinstance(amount, int) or isinstance(amount, bool) or not isinstance(currency, str):
        return None
    return f"{label}: {format_minor_amount(amount, currency)}"


def _display_text(value: object, tools: dict[str, Any]) -> str | None:
    text = _string(value)
    if text is None:
        return None
    payment = _mapping(tools.get("payment_state_snapshot"))
    policy = _mapping(tools.get("merchant_recovery_policy"))
    currency = payment.get("currency")
    if not isinstance(currency, str):
        currency = "INR"
    for amount in (payment.get("amount_minor"), policy.get("automatic_amount_limit_minor")):
        if isinstance(amount, int) and not isinstance(amount, bool):
            text = text.replace(str(amount), format_minor_amount(amount, currency))
    return text
