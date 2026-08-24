from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.domain.incidents import IncidentSeverity
from app.domain.payments import PaymentState


class RecoveryCaseStatus(StrEnum):
    OPEN = "open"
    PLANNING = "planning"
    READY = "ready"
    EXECUTING = "executing"
    WAITING = "waiting"
    RECOVERED = "recovered"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


class RecoveryActionType(StrEnum):
    CREATE_PAYMENT_LINK = "create_payment_link"
    SEND_RECOVERY_MESSAGE = "send_recovery_message"
    OFFER_ALTERNATE_METHOD = "offer_alternate_method"
    WAIT = "wait"
    ESCALATE_HUMAN = "escalate_human"
    STOP_RECOVERY = "stop_recovery"


class RecoveryChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class RecoveryPolicyOutcome(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"
    STOP = "stop"


class RecoveryGuardrail(StrEnum):
    PAYMENT_ALREADY_COMPLETED = "payment_already_completed"
    LATE_AUTHORIZATION_DETECTED = "late_authorization_detected"
    CASE_TERMINAL = "case_terminal"
    CASE_ALREADY_ESCALATED = "case_already_escalated"
    MAX_ATTEMPTS_REACHED = "max_attempts_reached"
    QUIET_PERIOD_ACTIVE = "quiet_period_active"
    INCIDENT_CIRCUIT_BREAKER = "incident_circuit_breaker"
    DUPLICATE_PAYMENT_LINK = "duplicate_payment_link"
    CONTACT_CONSENT_MISSING = "contact_consent_missing"
    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    AUTOMATIC_AMOUNT_LIMIT = "automatic_amount_limit"
    AGENT_REQUESTED_ESCALATION = "agent_requested_escalation"
    AGENT_REQUESTED_STOP = "agent_requested_stop"


CUSTOMER_CONTACT_ACTIONS: Final = frozenset(
    {
        RecoveryActionType.SEND_RECOVERY_MESSAGE,
        RecoveryActionType.OFFER_ALTERNATE_METHOD,
    },
)


def _require_timezone_aware(
    value: datetime,
    *,
    field_name: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware",
        )


def _normalize_required_text(
    value: str,
    *,
    field_name: str,
) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")

    return normalized


@dataclass(frozen=True, slots=True)
class RecoveryCaseSnapshot:
    case_id: UUID
    payment_attempt_id: UUID
    provider_payment_id: str

    payment_state: PaymentState
    amount_minor: int
    currency: str
    payment_method: str | None

    status: RecoveryCaseStatus
    recovery_attempt_count: int
    customer_contact_allowed: bool

    last_customer_contact_at: datetime | None = None
    active_payment_link_id: str | None = None
    active_incident_severity: IncidentSeverity | None = None
    late_authorization_detected_at: datetime | None = None
    recovered_at: datetime | None = None

    def __post_init__(self) -> None:
        provider_payment_id = _normalize_required_text(
            self.provider_payment_id,
            field_name="Provider payment ID",
        )
        object.__setattr__(
            self,
            "provider_payment_id",
            provider_payment_id,
        )

        if self.amount_minor <= 0:
            raise ValueError(
                "Payment amount must be positive",
            )

        currency = self.currency.strip().upper()

        if len(currency) != 3:
            raise ValueError(
                "Currency must be a three-letter code",
            )

        object.__setattr__(
            self,
            "currency",
            currency,
        )

        if self.payment_method is not None:
            normalized_method = self.payment_method.strip().casefold()

            object.__setattr__(
                self,
                "payment_method",
                normalized_method or None,
            )

        if self.recovery_attempt_count < 0:
            raise ValueError(
                "Recovery attempt count cannot be negative",
            )

        if self.active_payment_link_id is not None:
            normalized_link_id = self.active_payment_link_id.strip()

            object.__setattr__(
                self,
                "active_payment_link_id",
                normalized_link_id or None,
            )

        timestamp_fields = (
            (
                "Last customer contact",
                self.last_customer_contact_at,
            ),
            (
                "Late authorization detection",
                self.late_authorization_detected_at,
            ),
            (
                "Recovery timestamp",
                self.recovered_at,
            ),
        )

        for field_name, timestamp in timestamp_fields:
            if timestamp is not None:
                _require_timezone_aware(
                    timestamp,
                    field_name=field_name,
                )

        if self.status is RecoveryCaseStatus.RECOVERED and self.recovered_at is None:
            raise ValueError(
                "Recovered case requires recovery timestamp",
            )


@dataclass(frozen=True, slots=True)
class RecoveryActionProposal:
    action_type: RecoveryActionType
    reason: str

    amount_minor: int | None = None
    currency: str | None = None
    channel: RecoveryChannel | None = None
    target_payment_method: str | None = None
    execute_after: datetime | None = None

    def __post_init__(self) -> None:
        reason = _normalize_required_text(
            self.reason,
            field_name="Proposal reason",
        )
        object.__setattr__(
            self,
            "reason",
            reason,
        )

        if self.amount_minor is not None and self.amount_minor <= 0:
            raise ValueError(
                "Proposed amount must be positive",
            )

        if self.currency is not None:
            currency = self.currency.strip().upper()

            if len(currency) != 3:
                raise ValueError(
                    "Currency must be a three-letter code",
                )

            object.__setattr__(
                self,
                "currency",
                currency,
            )

        if self.target_payment_method is not None:
            target_method = self.target_payment_method.strip().casefold()

            object.__setattr__(
                self,
                "target_payment_method",
                target_method or None,
            )

        if self.execute_after is not None:
            _require_timezone_aware(
                self.execute_after,
                field_name="Execution time",
            )

        if self.action_type is RecoveryActionType.CREATE_PAYMENT_LINK and (
            self.amount_minor is None or self.currency is None
        ):
            raise ValueError(
                "Payment-link proposal requires amount and currency",
            )

        if self.action_type in CUSTOMER_CONTACT_ACTIONS and self.channel is None:
            raise ValueError(
                "Customer-contact proposal requires a channel",
            )

        if self.action_type is RecoveryActionType.WAIT and self.execute_after is None:
            raise ValueError(
                "Wait proposal requires execution time",
            )


@dataclass(frozen=True, slots=True)
class RecoveryPolicyDecision:
    outcome: RecoveryPolicyOutcome
    guardrails: tuple[RecoveryGuardrail, ...]
    explanation: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        explanation = _normalize_required_text(
            self.explanation,
            field_name="Policy explanation",
        )
        object.__setattr__(
            self,
            "explanation",
            explanation,
        )

        _require_timezone_aware(
            self.evaluated_at,
            field_name="Policy evaluation time",
        )

        if self.outcome is RecoveryPolicyOutcome.ALLOW and self.guardrails:
            raise ValueError(
                "Allowed decision cannot contain guardrail violations",
            )

        if self.outcome is not RecoveryPolicyOutcome.ALLOW and not self.guardrails:
            raise ValueError(
                "Non-allowed decision requires guardrail evidence",
            )
