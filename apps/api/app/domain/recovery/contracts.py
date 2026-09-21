"""Versioned, provider-neutral contracts for evidence-grounded recovery.

These contracts intentionally do not alter the current recovery runtime.  They
define the safety boundary that the payment-truth, investigator and execution
phases will adopt incrementally.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from string import hexdigits
from uuid import UUID


class PaymentEvidenceSource(StrEnum):
    PROVIDER_PAYMENT_API = "provider_payment_api"
    PROVIDER_ORDER_API = "provider_order_api"
    VERIFIED_WEBHOOK = "verified_webhook"
    MERCHANT_DATABASE = "merchant_database"
    RECOVERY_STATE = "recovery_state"
    RECONCILIATION = "reconciliation"


class PaymentTruthState(StrEnum):
    PAYMENT_CONFIRMED = "payment_confirmed"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_PENDING = "payment_pending"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SOURCE_CONFLICT = "source_conflict"
    LATE_AUTHORIZATION = "late_authorization"
    RECOVERY_ALREADY_ACTIVE = "recovery_already_active"
    RECOVERY_CONFIRMED = "recovery_confirmed"
    MANUAL_INVESTIGATION_REQUIRED = "manual_investigation_required"


class InvestigationHypothesisStatus(StrEnum):
    OPEN = "open"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class RecoveryIntentAction(StrEnum):
    WAIT_FOR_AUTH = "wait_for_auth"
    RETRY_LATER = "retry_later"
    CREATE_PAYMENT_LINK = "create_payment_link"
    CHANGE_METHOD = "change_method"
    ESCALATE = "escalate"
    DO_NOT_RECOVER = "do_not_recover"


class RecoveryAuthorization(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ProviderActionStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    CANCELLED_STALE = "cancelled_stale"
    VERIFIED = "verified"


def _required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _positive_version(value: int, *, field_name: str) -> None:
    if value < 1:
        raise ValueError(f"{field_name} must be positive")


def _unique_texts(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _sha256(value: str, *, field_name: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(character not in hexdigits for character in normalized):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return normalized


@dataclass(frozen=True, slots=True)
class PaymentEvidence:
    evidence_id: str
    case_id: UUID
    source: PaymentEvidenceSource
    fact_name: str
    fact_value: str
    observed_at: datetime
    content_sha256: str
    event_at: datetime | None = None
    fresh_until: datetime | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _required_text(self.evidence_id, field_name="Evidence ID"),
        )
        object.__setattr__(
            self,
            "fact_name",
            _required_text(self.fact_name, field_name="Evidence fact name"),
        )
        object.__setattr__(
            self,
            "fact_value",
            _required_text(self.fact_value, field_name="Evidence fact value"),
        )
        object.__setattr__(
            self,
            "content_sha256",
            _sha256(self.content_sha256, field_name="Evidence content hash"),
        )
        _aware(self.observed_at, field_name="Evidence observation time")
        for field_name, value in (
            ("Evidence event time", self.event_at),
            ("Evidence freshness deadline", self.fresh_until),
        ):
            if value is not None:
                _aware(value, field_name=field_name)
        if self.fresh_until is not None and self.fresh_until <= self.observed_at:
            raise ValueError("Evidence freshness deadline must follow observation time")


@dataclass(frozen=True, slots=True)
class PaymentTruthSnapshot:
    case_id: UUID
    version: int
    state: PaymentTruthState
    evidence_refs: tuple[str, ...]
    resolved_at: datetime
    conflict_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _positive_version(self.version, field_name="Truth version")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_texts(self.evidence_refs, field_name="Truth evidence references"),
        )
        _aware(self.resolved_at, field_name="Truth resolution time")
        conflicts = tuple(
            dict.fromkeys(code.strip() for code in self.conflict_codes if code.strip())
        )
        object.__setattr__(self, "conflict_codes", conflicts)
        if self.state is PaymentTruthState.SOURCE_CONFLICT and not conflicts:
            raise ValueError("Source-conflict truth requires at least one conflict code")
        if self.state is not PaymentTruthState.SOURCE_CONFLICT and conflicts:
            raise ValueError("Conflict codes are valid only for source-conflict truth")


@dataclass(frozen=True, slots=True)
class AIClaim:
    claim_id: str
    statement: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "claim_id",
            _required_text(self.claim_id, field_name="Claim ID"),
        )
        object.__setattr__(
            self,
            "statement",
            _required_text(self.statement, field_name="Claim statement"),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_texts(self.evidence_refs, field_name="Claim evidence references"),
        )


@dataclass(frozen=True, slots=True)
class InvestigationHypothesis:
    hypothesis_id: str
    statement: str
    status: InvestigationHypothesisStatus
    supporting_evidence_refs: tuple[str, ...] = ()
    contradicting_evidence_refs: tuple[str, ...] = ()
    missing_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "hypothesis_id",
            _required_text(self.hypothesis_id, field_name="Hypothesis ID"),
        )
        object.__setattr__(
            self,
            "statement",
            _required_text(self.statement, field_name="Hypothesis statement"),
        )
        for attribute in (
            "supporting_evidence_refs",
            "contradicting_evidence_refs",
            "missing_questions",
        ):
            values = tuple(
                dict.fromkeys(item.strip() for item in getattr(self, attribute) if item.strip())
            )
            object.__setattr__(self, attribute, values)
        if (
            self.status is InvestigationHypothesisStatus.CONFIRMED
            and not self.supporting_evidence_refs
        ):
            raise ValueError("Confirmed hypothesis requires supporting evidence")
        if (
            self.status is InvestigationHypothesisStatus.REJECTED
            and not self.contradicting_evidence_refs
        ):
            raise ValueError("Rejected hypothesis requires contradicting evidence")


@dataclass(frozen=True, slots=True)
class RecoveryIntent:
    intent_id: UUID
    case_id: UUID
    case_version: int
    truth_version: int
    action: RecoveryIntentAction
    evidence_refs: tuple[str, ...]
    rationale_claim_ids: tuple[str, ...]
    proposed_at: datetime
    execute_after: datetime | None = None

    def __post_init__(self) -> None:
        _positive_version(self.case_version, field_name="Case version")
        _positive_version(self.truth_version, field_name="Truth version")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_texts(self.evidence_refs, field_name="Intent evidence references"),
        )
        object.__setattr__(
            self,
            "rationale_claim_ids",
            _unique_texts(self.rationale_claim_ids, field_name="Intent rationale claims"),
        )
        _aware(self.proposed_at, field_name="Intent proposal time")
        if self.execute_after is not None:
            _aware(self.execute_after, field_name="Intent execution time")
            if self.execute_after < self.proposed_at:
                raise ValueError("Intent execution time cannot precede proposal time")


@dataclass(frozen=True, slots=True)
class PolicyDecisionContract:
    authorization: RecoveryAuthorization
    reason_code: str
    evaluated_case_version: int
    evaluated_truth_version: int
    evaluated_at: datetime
    check_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_code",
            _required_text(self.reason_code, field_name="Policy reason code"),
        )
        _positive_version(self.evaluated_case_version, field_name="Evaluated case version")
        _positive_version(self.evaluated_truth_version, field_name="Evaluated truth version")
        object.__setattr__(
            self,
            "check_codes",
            _unique_texts(self.check_codes, field_name="Policy check codes"),
        )
        _aware(self.evaluated_at, field_name="Policy evaluation time")


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    approval_id: UUID
    case_id: UUID
    case_version: int
    truth_version: int
    action: RecoveryIntentAction
    amount_minor: int
    evidence_digest: str
    granted_by: str
    granted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _positive_version(self.case_version, field_name="Approval case version")
        _positive_version(self.truth_version, field_name="Approval truth version")
        if self.amount_minor <= 0:
            raise ValueError("Approval amount must be positive")
        object.__setattr__(
            self,
            "evidence_digest",
            _sha256(self.evidence_digest, field_name="Approval evidence digest"),
        )
        object.__setattr__(
            self,
            "granted_by",
            _required_text(self.granted_by, field_name="Approval grantor"),
        )
        _aware(self.granted_at, field_name="Approval grant time")
        _aware(self.expires_at, field_name="Approval expiry time")
        if self.expires_at <= self.granted_at:
            raise ValueError("Approval expiry must follow grant time")


@dataclass(frozen=True, slots=True)
class ProviderActionAttempt:
    attempt_id: UUID
    intent_id: UUID
    idempotency_key: str
    status: ProviderActionStatus
    created_at: datetime
    provider_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "idempotency_key",
            _sha256(self.idempotency_key, field_name="Action idempotency key"),
        )
        _aware(self.created_at, field_name="Action attempt creation time")
        if self.provider_reference is not None:
            object.__setattr__(
                self,
                "provider_reference",
                _required_text(self.provider_reference, field_name="Provider reference"),
            )
        if self.status is ProviderActionStatus.VERIFIED and self.provider_reference is None:
            raise ValueError("Verified provider action requires a provider reference")


@dataclass(frozen=True, slots=True)
class RecoveryReceipt:
    receipt_id: UUID
    case_id: UUID
    truth_version: int
    evidence_digest: str
    decision_digest: str
    receipt_hash: str
    created_at: datetime
    previous_receipt_hash: str | None = None
    action_attempt_id: UUID | None = None

    def __post_init__(self) -> None:
        _positive_version(self.truth_version, field_name="Receipt truth version")
        for attribute, field_name in (
            ("evidence_digest", "Receipt evidence digest"),
            ("decision_digest", "Receipt decision digest"),
            ("receipt_hash", "Receipt hash"),
        ):
            object.__setattr__(
                self,
                attribute,
                _sha256(getattr(self, attribute), field_name=field_name),
            )
        if self.previous_receipt_hash is not None:
            object.__setattr__(
                self,
                "previous_receipt_hash",
                _sha256(
                    self.previous_receipt_hash,
                    field_name="Previous receipt hash",
                ),
            )
        _aware(self.created_at, field_name="Receipt creation time")
