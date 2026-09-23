"""Deterministic, evidence-first payment truth resolution."""

from dataclasses import dataclass
from datetime import datetime
from string import hexdigits

from app.domain.recovery.contracts import PaymentEvidenceSource, PaymentTruthState


@dataclass(frozen=True, slots=True)
class PaymentTruthEvidenceFact:
    evidence_id: str
    source: PaymentEvidenceSource
    fact_name: str
    fact_value: str
    content_sha256: str
    observed_at: datetime
    event_at: datetime | None = None
    fresh_until: datetime | None = None
    verified: bool = False
    reliability: str = "corroborating"
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "fact_name", "fact_value"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be empty")
        digest = self.content_sha256.strip().casefold()
        if len(digest) != 64 or any(character not in hexdigits for character in digest):
            raise ValueError("content_sha256 must be a SHA-256 hex digest")
        object.__setattr__(self, "content_sha256", digest)
        for field_name in ("observed_at", "event_at", "fresh_until"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.reliability not in {"authoritative", "corroborating", "weak"}:
            raise ValueError("reliability must be authoritative, corroborating, or weak")

    def is_fresh_at(self, resolved_at: datetime) -> bool:
        return self.fresh_until is None or self.fresh_until >= resolved_at


@dataclass(frozen=True, slots=True)
class PaymentTruthDecision:
    state: PaymentTruthState
    evidence_refs: tuple[str, ...]
    conflict_codes: tuple[str, ...] = ()


_CONFIRMED_STATUSES = frozenset({"captured", "paid", "refunded"})
_FAILED_STATUSES = frozenset({"failed"})
_PENDING_STATUSES = frozenset({"created", "pending", "attempted", "authorized"})
_ACTIVE_RECOVERY_STATUSES = frozenset(
    {"active", "ready", "awaiting_approval", "scheduled", "executing", "waiting"}
)
_CONFIRMED_RECOVERY_STATUSES = frozenset({"recovered", "paid", "verified"})
_TRUE_VALUES = frozenset({"1", "true", "yes"})
_FALSE_VALUES = frozenset({"0", "false", "no"})


def resolve_payment_truth(
    evidence: tuple[PaymentTruthEvidenceFact, ...],
    *,
    resolved_at: datetime,
) -> PaymentTruthDecision:
    """Resolve truth without trusting source order or an LLM opinion."""
    if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
        raise ValueError("Truth resolution time must be timezone-aware")

    usable = tuple(item for item in evidence if item.verified and item.is_fresh_at(resolved_at))
    refs = tuple(sorted({item.evidence_id for item in usable}))
    if not usable:
        return PaymentTruthDecision(
            state=PaymentTruthState.OUTCOME_UNKNOWN,
            evidence_refs=(),
        )

    provider_unavailable = any(item.unavailable_reason for item in usable)
    provider_payment_missing = any(
        item.fact_name.strip().casefold() == "provider.matching_payment_count"
        and item.fact_value.strip() == "0"
        for item in usable
    )

    payment_statuses = {
        item.fact_value.strip().casefold()
        for item in usable
        if item.fact_name.strip().casefold() in {"payment.status", "order.status"}
    }
    recovery_statuses = {
        item.fact_value.strip().casefold()
        for item in usable
        if item.fact_name.strip().casefold() == "recovery.status"
    }
    late_authorization = any(
        item.fact_name.strip().casefold() == "payment.late_authorization"
        and item.fact_value.strip().casefold() in _TRUE_VALUES
        for item in usable
    )
    identity_mismatches = sorted(
        {
            item.fact_name.strip().casefold().removeprefix("identity.")
            for item in usable
            if item.fact_name.strip().casefold().startswith("identity.")
            and item.fact_value.strip().casefold() in _FALSE_VALUES
        },
    )

    confirmed = bool(payment_statuses & _CONFIRMED_STATUSES)
    authorized = "authorized" in payment_statuses
    failed = bool(payment_statuses & _FAILED_STATUSES)
    pending = bool(payment_statuses & _PENDING_STATUSES)

    conflict_codes = [f"identity_{name}_mismatch" for name in identity_mismatches]
    if confirmed and failed and not late_authorization:
        conflict_codes.append("confirmed_and_failed_payment_evidence")
    if conflict_codes:
        return PaymentTruthDecision(
            state=PaymentTruthState.SOURCE_CONFLICT,
            evidence_refs=refs,
            conflict_codes=tuple(conflict_codes),
        )
    if (provider_unavailable or provider_payment_missing) and not confirmed:
        return PaymentTruthDecision(
            state=PaymentTruthState.MANUAL_INVESTIGATION_REQUIRED,
            evidence_refs=refs,
        )
    if recovery_statuses & _CONFIRMED_RECOVERY_STATUSES:
        return PaymentTruthDecision(PaymentTruthState.RECOVERY_CONFIRMED, refs)
    if late_authorization and (confirmed or authorized):
        return PaymentTruthDecision(PaymentTruthState.LATE_AUTHORIZATION, refs)
    if confirmed:
        return PaymentTruthDecision(PaymentTruthState.PAYMENT_CONFIRMED, refs)
    if recovery_statuses & _ACTIVE_RECOVERY_STATUSES:
        return PaymentTruthDecision(PaymentTruthState.RECOVERY_ALREADY_ACTIVE, refs)
    if failed:
        return PaymentTruthDecision(PaymentTruthState.PAYMENT_FAILED, refs)
    if pending:
        return PaymentTruthDecision(PaymentTruthState.PAYMENT_PENDING, refs)
    return PaymentTruthDecision(PaymentTruthState.MANUAL_INVESTIGATION_REQUIRED, refs)
