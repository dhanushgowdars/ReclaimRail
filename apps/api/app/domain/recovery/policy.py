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
