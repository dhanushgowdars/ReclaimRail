from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeProof,
    RecoveryOutcomeStatus,
)


class RecoveryPaymentLinkOutcomeState(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REVERSED = "reversed"


ZERO_AMOUNT_LINK_STATES: Final = frozenset(
    {
        RecoveryPaymentLinkOutcomeState.PENDING,
        RecoveryPaymentLinkOutcomeState.EXPIRED,
        RecoveryPaymentLinkOutcomeState.CANCELLED,
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
        raise ValueError(
            f"{field_name} cannot be empty",
        )

    return normalized


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeReconciliationInput:
    recovery_case_id: UUID
    payment_attempt_id: UUID
    recovery_action_id: UUID

    provider_payment_id: str
    payment_link_id: str

    original_amount_minor: int
    currency: str

    payment_link_state: RecoveryPaymentLinkOutcomeState
    observed_at: datetime
    evidence_event_ids: tuple[str, ...]

    payment_link_paid_amount_minor: int = 0
    payment_link_reversed_minor: int = 0
    late_authorization_detected_at: datetime | None = None

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

        payment_link_id = _normalize_required_text(
            self.payment_link_id,
            field_name="Payment Link ID",
        )
        object.__setattr__(
            self,
            "payment_link_id",
            payment_link_id,
        )

        if self.original_amount_minor <= 0:
            raise ValueError(
                "Original payment amount must be positive",
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

        _require_timezone_aware(
            self.observed_at,
            field_name="Outcome observation time",
        )

        if self.late_authorization_detected_at is not None:
            _require_timezone_aware(
                self.late_authorization_detected_at,
                field_name="Late authorization detection time",
            )

        evidence_event_ids = tuple(
            _normalize_required_text(
                event_id,
                field_name="Evidence event ID",
            )
            for event_id in self.evidence_event_ids
        )

        if not evidence_event_ids:
            raise ValueError(
                "Outcome reconciliation requires evidence event IDs",
            )

        if len(set(evidence_event_ids)) != len(
            evidence_event_ids,
        ):
            raise ValueError(
                "Evidence event IDs must be unique",
            )

        object.__setattr__(
            self,
            "evidence_event_ids",
            evidence_event_ids,
        )

        if self.payment_link_paid_amount_minor < 0:
            raise ValueError(
                "Payment Link paid amount cannot be negative",
            )

        if self.payment_link_reversed_minor < 0:
            raise ValueError(
                "Payment Link reversed amount cannot be negative",
            )

        if self.payment_link_paid_amount_minor > self.original_amount_minor:
            raise ValueError(
                ("Payment Link paid amount cannot exceed original payment amount"),
            )

        if self.payment_link_reversed_minor > self.payment_link_paid_amount_minor:
            raise ValueError(
                ("Payment Link reversed amount cannot exceed Payment Link paid amount"),
            )

        if self.payment_link_state in ZERO_AMOUNT_LINK_STATES and (
            self.payment_link_paid_amount_minor != 0 or self.payment_link_reversed_minor != 0
        ):
            raise ValueError(
                "Unpaid Payment Link state cannot contain paid amounts",
            )

        if self.payment_link_state is RecoveryPaymentLinkOutcomeState.PAID and (
            self.payment_link_paid_amount_minor <= 0
        ):
            raise ValueError(
                "Paid Payment Link state requires a positive paid amount",
            )

        if self.payment_link_state is RecoveryPaymentLinkOutcomeState.REVERSED and (
            self.payment_link_paid_amount_minor <= 0 or self.payment_link_reversed_minor <= 0
        ):
            raise ValueError(
                ("Reversed Payment Link state requires paid and reversed amounts"),
            )


def reconcile_recovery_outcome(
    value: RecoveryOutcomeReconciliationInput,
) -> RecoveryOutcomeProof:
    """
    Create a conservative, evidence-backed outcome classification.

    A late authorization is never credited as recovered revenue. It becomes
    duplicate-collection prevention only when the recovery Payment Link is
    confirmed cancelled.
    """
    if value.late_authorization_detected_at is not None:
        if value.payment_link_state is RecoveryPaymentLinkOutcomeState.CANCELLED:
            return RecoveryOutcomeProof(
                recovery_case_id=value.recovery_case_id,
                payment_attempt_id=value.payment_attempt_id,
                provider_payment_id=value.provider_payment_id,
                status=(RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED),
                attribution=(RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY),
                occurred_at=value.observed_at,
                original_amount_minor=value.original_amount_minor,
                currency=value.currency,
                recovery_action_id=value.recovery_action_id,
                payment_link_id=value.payment_link_id,
                duplicate_collection_prevented_minor=(value.original_amount_minor),
                evidence_event_ids=value.evidence_event_ids,
            )

        return RecoveryOutcomeProof(
            recovery_case_id=value.recovery_case_id,
            payment_attempt_id=value.payment_attempt_id,
            provider_payment_id=value.provider_payment_id,
            status=RecoveryOutcomeStatus.UNRESOLVED,
            attribution=RecoveryOutcomeAttribution.NONE,
            occurred_at=value.observed_at,
            original_amount_minor=value.original_amount_minor,
            currency=value.currency,
            recovery_action_id=value.recovery_action_id,
            payment_link_id=value.payment_link_id,
            evidence_event_ids=value.evidence_event_ids,
        )

    if value.payment_link_state is RecoveryPaymentLinkOutcomeState.REVERSED:
        return RecoveryOutcomeProof(
            recovery_case_id=value.recovery_case_id,
            payment_attempt_id=value.payment_attempt_id,
            provider_payment_id=value.provider_payment_id,
            status=RecoveryOutcomeStatus.REVERSED,
            attribution=RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
            occurred_at=value.observed_at,
            original_amount_minor=value.original_amount_minor,
            currency=value.currency,
            recovery_action_id=value.recovery_action_id,
            payment_link_id=value.payment_link_id,
            gross_recovered_minor=value.payment_link_paid_amount_minor,
            reversed_minor=value.payment_link_reversed_minor,
            evidence_event_ids=value.evidence_event_ids,
        )

    if value.payment_link_state is RecoveryPaymentLinkOutcomeState.PAID:
        return RecoveryOutcomeProof(
            recovery_case_id=value.recovery_case_id,
            payment_attempt_id=value.payment_attempt_id,
            provider_payment_id=value.provider_payment_id,
            status=RecoveryOutcomeStatus.RECOVERED,
            attribution=RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
            occurred_at=value.observed_at,
            original_amount_minor=value.original_amount_minor,
            currency=value.currency,
            recovery_action_id=value.recovery_action_id,
            payment_link_id=value.payment_link_id,
            gross_recovered_minor=value.payment_link_paid_amount_minor,
            evidence_event_ids=value.evidence_event_ids,
        )

    if value.payment_link_state is RecoveryPaymentLinkOutcomeState.EXPIRED:
        status = RecoveryOutcomeStatus.PAYMENT_LINK_EXPIRED
    elif value.payment_link_state is RecoveryPaymentLinkOutcomeState.CANCELLED:
        status = RecoveryOutcomeStatus.PAYMENT_LINK_CANCELLED
    else:
        status = RecoveryOutcomeStatus.PAYMENT_LINK_PENDING

    return RecoveryOutcomeProof(
        recovery_case_id=value.recovery_case_id,
        payment_attempt_id=value.payment_attempt_id,
        provider_payment_id=value.provider_payment_id,
        status=status,
        attribution=RecoveryOutcomeAttribution.NONE,
        occurred_at=value.observed_at,
        original_amount_minor=value.original_amount_minor,
        currency=value.currency,
        recovery_action_id=value.recovery_action_id,
        payment_link_id=value.payment_link_id,
        evidence_event_ids=value.evidence_event_ids,
    )
