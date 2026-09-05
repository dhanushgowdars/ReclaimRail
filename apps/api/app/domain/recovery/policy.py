from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.domain.incidents import IncidentSeverity
from app.domain.payments import STOP_RECOVERY_STATES
from app.domain.recovery.models import (
    CUSTOMER_CONTACT_ACTIONS,
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryGuardrail,
    RecoveryPolicyDecision,
    RecoveryPolicyOutcome,
)

TERMINAL_CASE_STATUSES: Final = frozenset(
    {
        RecoveryCaseStatus.RECOVERED,
        RecoveryCaseStatus.EXHAUSTED,
        RecoveryCaseStatus.CANCELLED,
    },
)

AUTOMATED_INTERVENTION_ACTIONS: Final = frozenset(
    {
        RecoveryActionType.CREATE_PAYMENT_LINK,
        RecoveryActionType.SEND_RECOVERY_MESSAGE,
        RecoveryActionType.OFFER_ALTERNATE_METHOD,
    },
)


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    maximum_recovery_attempts: int = 3
    customer_quiet_period: timedelta = timedelta(hours=4)
    # Hard execution boundary. The lower, independently configured approval
    # threshold pauses an otherwise allowed action for operator review.
    automatic_amount_limit_minor: int = 5_000_000
    circuit_breaker_severities: tuple[IncidentSeverity, ...] = (
        IncidentSeverity.HIGH,
        IncidentSeverity.CRITICAL,
    )

    def __post_init__(self) -> None:
        if self.maximum_recovery_attempts < 1:
            raise ValueError(
                "Maximum recovery attempts must be positive",
            )

        if self.customer_quiet_period < timedelta(0):
            raise ValueError(
                "Customer quiet period cannot be negative",
            )

        if self.automatic_amount_limit_minor < 1:
            raise ValueError(
                "Automatic amount limit must be positive",
            )

        if not self.circuit_breaker_severities:
            raise ValueError(
                "Circuit breaker must include at least one severity",
            )


DEFAULT_RECOVERY_POLICY: Final = RecoveryPolicy()


@dataclass(frozen=True, slots=True)
class RecoveryPolicyCheck:
    """One display-safe, immutable evaluation performed by policy.

    Guardrail codes only describe failures.  This record also preserves the
    checks that passed or did not apply, so an Allow decision is explainable.
    """

    code: str
    label: str
    actual_value: str
    rule: str
    result: str

    def __post_init__(self) -> None:
        if self.result not in {
            "passed",
            "failed",
            "not_applicable",
            "requires_review",
        }:
            raise ValueError("Policy check result is invalid")

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "label": self.label,
            "actual_value": self.actual_value,
            "rule": self.rule,
            "result": self.result,
        }


def _require_timezone_aware(
    value: datetime,
    *,
    field_name: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware",
        )


def _ordered_unique_guardrails(
    guardrails: Sequence[RecoveryGuardrail],
) -> tuple[RecoveryGuardrail, ...]:
    return tuple(dict.fromkeys(guardrails))


def _build_decision(
    *,
    outcome: RecoveryPolicyOutcome,
    guardrails: Sequence[RecoveryGuardrail],
    evaluated_at: datetime,
) -> RecoveryPolicyDecision:
    ordered_guardrails = _ordered_unique_guardrails(
        guardrails,
    )

    if outcome is RecoveryPolicyOutcome.ALLOW:
        explanation = "All deterministic recovery guardrails passed"
    else:
        outcome_labels = {
            RecoveryPolicyOutcome.BLOCK: "Blocked",
            RecoveryPolicyOutcome.ESCALATE: "Escalated",
            RecoveryPolicyOutcome.STOP: "Stopped",
        }

        guardrail_codes = ", ".join(guardrail.value for guardrail in ordered_guardrails)

        explanation = f"{outcome_labels[outcome]} by deterministic guardrails: {guardrail_codes}"

    return RecoveryPolicyDecision(
        outcome=outcome,
        guardrails=ordered_guardrails,
        explanation=explanation,
        evaluated_at=evaluated_at,
    )


def evaluate_recovery_proposal(
    case: RecoveryCaseSnapshot,
    proposal: RecoveryActionProposal,
    *,
    evaluated_at: datetime,
    policy: RecoveryPolicy = DEFAULT_RECOVERY_POLICY,
) -> RecoveryPolicyDecision:
    """Evaluate an agent proposal without trusting the agent itself."""

    _require_timezone_aware(
        evaluated_at,
        field_name="Policy evaluation time",
    )

    stop_guardrails: list[RecoveryGuardrail] = []

    if case.status in TERMINAL_CASE_STATUSES:
        stop_guardrails.append(
            RecoveryGuardrail.CASE_TERMINAL,
        )

    if case.payment_state in STOP_RECOVERY_STATES:
        stop_guardrails.append(
            RecoveryGuardrail.PAYMENT_ALREADY_COMPLETED,
        )

    if case.late_authorization_detected_at is not None:
        stop_guardrails.append(
            RecoveryGuardrail.LATE_AUTHORIZATION_DETECTED,
        )

    if stop_guardrails:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.STOP,
            guardrails=stop_guardrails,
            evaluated_at=evaluated_at,
        )

    if proposal.action_type is RecoveryActionType.STOP_RECOVERY:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.STOP,
            guardrails=(RecoveryGuardrail.AGENT_REQUESTED_STOP,),
            evaluated_at=evaluated_at,
        )

    if case.status is RecoveryCaseStatus.ESCALATED:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.ESCALATE,
            guardrails=(RecoveryGuardrail.CASE_ALREADY_ESCALATED,),
            evaluated_at=evaluated_at,
        )

    if proposal.action_type is RecoveryActionType.ESCALATE_HUMAN:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.ESCALATE,
            guardrails=(RecoveryGuardrail.AGENT_REQUESTED_ESCALATION,),
            evaluated_at=evaluated_at,
        )

    if case.recovery_attempt_count >= policy.maximum_recovery_attempts:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.STOP,
            guardrails=(RecoveryGuardrail.MAX_ATTEMPTS_REACHED,),
            evaluated_at=evaluated_at,
        )

    block_guardrails: list[RecoveryGuardrail] = []
    escalate_guardrails: list[RecoveryGuardrail] = []

    if (
        proposal.action_type in AUTOMATED_INTERVENTION_ACTIONS
        and case.active_incident_severity in policy.circuit_breaker_severities
    ):
        block_guardrails.append(
            RecoveryGuardrail.INCIDENT_CIRCUIT_BREAKER,
        )

    if proposal.action_type is RecoveryActionType.CREATE_PAYMENT_LINK:
        if case.active_payment_link_id is not None:
            block_guardrails.append(
                RecoveryGuardrail.DUPLICATE_PAYMENT_LINK,
            )

        if proposal.amount_minor != case.amount_minor:
            block_guardrails.append(
                RecoveryGuardrail.AMOUNT_MISMATCH,
            )

        if proposal.currency != case.currency:
            block_guardrails.append(
                RecoveryGuardrail.CURRENCY_MISMATCH,
            )

        if (
            proposal.amount_minor is not None
            and proposal.amount_minor > policy.automatic_amount_limit_minor
        ):
            escalate_guardrails.append(
                RecoveryGuardrail.AUTOMATIC_AMOUNT_LIMIT,
            )

    if proposal.action_type in CUSTOMER_CONTACT_ACTIONS:
        if not case.customer_contact_allowed:
            block_guardrails.append(
                RecoveryGuardrail.CONTACT_CONSENT_MISSING,
            )

        if (
            case.last_customer_contact_at is not None
            and evaluated_at < case.last_customer_contact_at + policy.customer_quiet_period
        ):
            block_guardrails.append(
                RecoveryGuardrail.QUIET_PERIOD_ACTIVE,
            )

    if block_guardrails:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.BLOCK,
            guardrails=(
                *block_guardrails,
                *escalate_guardrails,
            ),
            evaluated_at=evaluated_at,
        )

    if escalate_guardrails:
        return _build_decision(
            outcome=RecoveryPolicyOutcome.ESCALATE,
            guardrails=escalate_guardrails,
            evaluated_at=evaluated_at,
        )

    return _build_decision(
        outcome=RecoveryPolicyOutcome.ALLOW,
        guardrails=(),
        evaluated_at=evaluated_at,
    )


def build_recovery_policy_checks(
    case: RecoveryCaseSnapshot,
    proposal: RecoveryActionProposal,
    *,
    evaluated_at: datetime,
    policy: RecoveryPolicy = DEFAULT_RECOVERY_POLICY,
) -> tuple[RecoveryPolicyCheck, ...]:
    """Describe every deterministic check evaluated for one proposal.

    This is deliberately derived from the same input snapshot as
    :func:`evaluate_recovery_proposal`; it is not a UI-side reconstruction.
    """

    _require_timezone_aware(
        evaluated_at,
        field_name="Policy evaluation time",
    )

    checks: list[RecoveryPolicyCheck] = []

    def append(
        code: str,
        label: str,
        actual_value: str,
        rule: str,
        passed: bool,
    ) -> None:
        checks.append(
            RecoveryPolicyCheck(
                code=code,
                label=label,
                actual_value=actual_value,
                rule=rule,
                result="passed" if passed else "failed",
            ),
        )

    def not_applicable(code: str, label: str, rule: str) -> None:
        checks.append(
            RecoveryPolicyCheck(
                code=code,
                label=label,
                actual_value="Not applicable to this action",
                rule=rule,
                result="not_applicable",
            ),
        )

    append(
        "case_not_terminal",
        "Case remains recoverable",
        case.status.value,
        "Terminal or cancelled cases stop recovery",
        case.status not in TERMINAL_CASE_STATUSES,
    )
    append(
        "payment_not_completed",
        "Original payment is not completed",
        case.payment_state.value,
        "Completed payment evidence stops recovery",
        case.payment_state not in STOP_RECOVERY_STATES,
    )
    append(
        "late_authorization_absent",
        "No late authorization detected",
        "Not detected" if case.late_authorization_detected_at is None else "Detected",
        "Late authorization stops unsafe recovery",
        case.late_authorization_detected_at is None,
    )
    append(
        "attempt_limit",
        "Recovery attempt limit",
        f"{case.recovery_attempt_count} of {policy.maximum_recovery_attempts}",
        f"Maximum {policy.maximum_recovery_attempts} recovery attempts",
        case.recovery_attempt_count < policy.maximum_recovery_attempts,
    )

    if proposal.action_type in AUTOMATED_INTERVENTION_ACTIONS:
        incident = case.active_incident_severity
        append(
            "incident_circuit_breaker",
            "Payment-rail incident circuit breaker",
            "No active incident" if incident is None else incident.value,
            "High or critical rail incidents block automated recovery",
            incident not in policy.circuit_breaker_severities,
        )
    else:
        not_applicable(
            "incident_circuit_breaker",
            "Payment-rail incident circuit breaker",
            "Applies to automated provider or customer interventions",
        )

    if proposal.action_type is RecoveryActionType.CREATE_PAYMENT_LINK:
        append(
            "no_duplicate_payment_link",
            "No existing payment link",
            "No active link" if case.active_payment_link_id is None else "Active link exists",
            "Only one active recovery payment link is permitted",
            case.active_payment_link_id is None,
        )
        append(
            "amount_matches_original",
            "Recovery amount matches original payment",
            f"Proposed {proposal.amount_minor}; original {case.amount_minor}",
            "Payment-link amount must exactly match the original payment",
            proposal.amount_minor == case.amount_minor,
        )
        append(
            "currency_matches_original",
            "Recovery currency matches original payment",
            f"Proposed {proposal.currency}; original {case.currency}",
            "Payment-link currency must exactly match the original payment",
            proposal.currency == case.currency,
        )
        append(
            "automatic_amount_limit",
            "Automatic amount boundary",
            f"{proposal.amount_minor} minor units; limit {policy.automatic_amount_limit_minor}",
            "Amounts above the hard automatic limit require escalation",
            proposal.amount_minor is not None
            and proposal.amount_minor <= policy.automatic_amount_limit_minor,
        )
    else:
        not_applicable(
            "no_duplicate_payment_link",
            "No existing payment link",
            "Applies only when creating a payment link",
        )
        not_applicable(
            "amount_matches_original",
            "Recovery amount matches original payment",
            "Applies only when creating a payment link",
        )
        not_applicable(
            "currency_matches_original",
            "Recovery currency matches original payment",
            "Applies only when creating a payment link",
        )
        not_applicable(
            "automatic_amount_limit",
            "Automatic amount boundary",
            "Applies only when creating a payment link",
        )

    if proposal.action_type in CUSTOMER_CONTACT_ACTIONS:
        append(
            "customer_contact_consent",
            "Customer contact consent",
            "Granted" if case.customer_contact_allowed else "Not granted",
            "Customer-contact actions require recorded consent",
            case.customer_contact_allowed,
        )
        quiet_until = (
            case.last_customer_contact_at + policy.customer_quiet_period
            if case.last_customer_contact_at is not None
            else None
        )
        append(
            "customer_quiet_period",
            "Customer contact quiet period",
            (
                "No previous customer contact"
                if quiet_until is None
                else (
                    f"Active until {quiet_until.isoformat()}"
                    if evaluated_at < quiet_until
                    else "Elapsed"
                )
            ),
            "Wait four hours after the most recent customer contact",
            quiet_until is None or evaluated_at >= quiet_until,
        )
    else:
        not_applicable(
            "customer_contact_consent",
            "Customer contact consent",
            "This action does not contact the customer",
        )
        not_applicable(
            "customer_quiet_period",
            "Customer contact quiet period",
            "This action does not contact the customer",
        )

    return tuple(checks)
