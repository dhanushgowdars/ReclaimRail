from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID


class RecoveryOutcomeStatus(StrEnum):
    PAYMENT_LINK_PENDING = "payment_link_pending"
    RECOVERED = "recovered"
    PAYMENT_LINK_EXPIRED = "payment_link_expired"
    PAYMENT_LINK_CANCELLED = "payment_link_cancelled"
    DUPLICATE_COLLECTION_PREVENTED = "duplicate_collection_prevented"
    REVERSED = "reversed"
    UNRESOLVED = "unresolved"


class RecoveryOutcomeAttribution(StrEnum):
    DIRECT_PAYMENT_LINK = "direct_payment_link"
    LATE_AUTHORIZATION_SAFETY = "late_authorization_safety"
    NONE = "none"


ZERO_IMPACT_OUTCOMES: Final = frozenset(
    {
        RecoveryOutcomeStatus.PAYMENT_LINK_PENDING,
        RecoveryOutcomeStatus.PAYMENT_LINK_EXPIRED,
        RecoveryOutcomeStatus.PAYMENT_LINK_CANCELLED,
        RecoveryOutcomeStatus.UNRESOLVED,
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
class RecoveryOutcomeProof:
    """Auditable, evidence-backed financial outcome for one recovery case."""

    recovery_case_id: UUID
    payment_attempt_id: UUID
    provider_payment_id: str

    status: RecoveryOutcomeStatus
    attribution: RecoveryOutcomeAttribution
    occurred_at: datetime

    original_amount_minor: int
    currency: str

    recovery_action_id: UUID | None = None
    payment_link_id: str | None = None
    provider_outcome_id: str | None = None

    gross_recovered_minor: int = 0
    reversed_minor: int = 0
    duplicate_collection_prevented_minor: int = 0

    evidence_event_ids: tuple[str, ...] = ()

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
            self.occurred_at,
            field_name="Outcome timestamp",
        )

        if self.payment_link_id is not None:
            payment_link_id = self.payment_link_id.strip()

            object.__setattr__(
                self,
                "payment_link_id",
                payment_link_id or None,
            )

        if self.provider_outcome_id is not None:
            provider_outcome_id = self.provider_outcome_id.strip()

            object.__setattr__(
                self,
                "provider_outcome_id",
                provider_outcome_id or None,
            )

        normalized_evidence_ids = tuple(
            _normalize_required_text(
                event_id,
                field_name="Evidence event ID",
            )
            for event_id in self.evidence_event_ids
        )

        if len(set(normalized_evidence_ids)) != len(
            normalized_evidence_ids,
        ):
            raise ValueError(
                "Evidence event IDs must be unique",
            )

        object.__setattr__(
            self,
            "evidence_event_ids",
            normalized_evidence_ids,
        )

        monetary_values = (
            (
                "Gross recovered amount",
                self.gross_recovered_minor,
            ),
            (
                "Reversed amount",
                self.reversed_minor,
            ),
            (
                "Duplicate collection prevented amount",
                self.duplicate_collection_prevented_minor,
            ),
        )

        for field_name, amount_minor in monetary_values:
            if amount_minor < 0:
                raise ValueError(
                    f"{field_name} cannot be negative",
                )

        if self.gross_recovered_minor > self.original_amount_minor:
            raise ValueError(
                "Recovered amount cannot exceed original payment amount",
            )

        if self.reversed_minor > self.gross_recovered_minor:
            raise ValueError(
                "Reversed amount cannot exceed recovered amount",
            )

        if self.duplicate_collection_prevented_minor > self.original_amount_minor:
            raise ValueError(
                ("Duplicate collection prevented amount cannot exceed original payment amount"),
            )

        if self.status is RecoveryOutcomeStatus.RECOVERED:
            if self.gross_recovered_minor <= 0:
                raise ValueError(
                    "Recovered outcome requires a positive recovered amount",
                )

            if self.attribution is not (RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK):
                raise ValueError(
                    ("Recovered outcome requires direct Payment Link attribution"),
                )

            if (
                self.recovery_action_id is None
                or self.payment_link_id is None
                or not self.evidence_event_ids
            ):
                raise ValueError(
                    ("Recovered outcome requires action, Payment Link, and evidence"),
                )

        if self.status is RecoveryOutcomeStatus.REVERSED:
            if self.gross_recovered_minor <= 0 or self.reversed_minor <= 0:
                raise ValueError(
                    "Reversed outcome requires recovered and reversed amounts",
                )

            if not self.evidence_event_ids:
                raise ValueError(
                    "Reversed outcome requires evidence",
                )

        if self.status is (RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED):
            if self.duplicate_collection_prevented_minor <= 0:
                raise ValueError(
                    ("Duplicate-prevention outcome requires a positive protected amount"),
                )

            if self.attribution is not (RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY):
                raise ValueError(
                    ("Duplicate-prevention outcome requires late-authorization safety attribution"),
                )

            if not self.evidence_event_ids:
                raise ValueError(
                    ("Duplicate-prevention outcome requires evidence"),
                )

        if self.status in ZERO_IMPACT_OUTCOMES:
            if (
                self.gross_recovered_minor != 0
                or self.reversed_minor != 0
                or self.duplicate_collection_prevented_minor != 0
            ):
                raise ValueError(
                    ("Zero-impact outcome cannot contain financial impact amounts"),
                )

            if self.attribution is not RecoveryOutcomeAttribution.NONE:
                raise ValueError(
                    "Zero-impact outcome requires no revenue attribution",
                )

    @property
    def net_recovered_minor(self) -> int:
        return self.gross_recovered_minor - self.reversed_minor

    @property
    def has_recovered_revenue(self) -> bool:
        return self.net_recovered_minor > 0
