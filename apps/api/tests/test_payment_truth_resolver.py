from datetime import UTC, datetime, timedelta

import pytest

from app.domain.payments.truth import PaymentTruthEvidenceFact, resolve_payment_truth
from app.domain.recovery.contracts import PaymentEvidenceSource, PaymentTruthState

NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)


def fact(
    evidence_id: str,
    name: str,
    value: str,
    *,
    source: PaymentEvidenceSource = PaymentEvidenceSource.VERIFIED_WEBHOOK,
    verified: bool = True,
    fresh_until: datetime | None = None,
) -> PaymentTruthEvidenceFact:
    return PaymentTruthEvidenceFact(
        evidence_id=evidence_id,
        source=source,
        fact_name=name,
        fact_value=value,
        content_sha256="a" * 64,
        observed_at=NOW,
        fresh_until=fresh_until,
        verified=verified,
    )


def test_verified_failure_resolves_payment_failed() -> None:
    decision = resolve_payment_truth(
        (fact("ev_failed", "payment.status", "failed"),),
        resolved_at=NOW,
    )

    assert decision.state is PaymentTruthState.PAYMENT_FAILED
    assert decision.evidence_refs == ("ev_failed",)
    assert decision.conflict_codes == ()


def test_unverified_or_stale_evidence_cannot_establish_failure() -> None:
    decision = resolve_payment_truth(
        (
            fact("ev_unverified", "payment.status", "failed", verified=False),
            fact(
                "ev_stale",
                "payment.status",
                "failed",
                fresh_until=NOW - timedelta(seconds=1),
            ),
        ),
        resolved_at=NOW,
    )

    assert decision.state is PaymentTruthState.OUTCOME_UNKNOWN
    assert decision.evidence_refs == ()


def test_confirmed_and_failed_sources_resolve_conflict() -> None:
    decision = resolve_payment_truth(
        (
            fact("ev_failed", "payment.status", "failed"),
            fact(
                "ev_captured",
                "payment.status",
                "captured",
                source=PaymentEvidenceSource.PROVIDER_PAYMENT_API,
            ),
        ),
        resolved_at=NOW,
    )

    assert decision.state is PaymentTruthState.SOURCE_CONFLICT
    assert decision.conflict_codes == ("confirmed_and_failed_payment_evidence",)


def test_late_authorization_is_explicit_safe_truth() -> None:
    decision = resolve_payment_truth(
        (
            fact("ev_failed", "payment.status", "failed"),
            fact("ev_authorized", "payment.status", "authorized"),
            fact("ev_late", "payment.late_authorization", "true"),
        ),
        resolved_at=NOW,
    )

    assert decision.state is PaymentTruthState.LATE_AUTHORIZATION


def test_identity_mismatch_fails_closed_to_source_conflict() -> None:
    decision = resolve_payment_truth(
        (
            fact("ev_failed", "payment.status", "failed"),
            fact("ev_amount", "identity.amount_match", "false"),
        ),
        resolved_at=NOW,
    )

    assert decision.state is PaymentTruthState.SOURCE_CONFLICT
    assert decision.conflict_codes == ("identity_amount_match_mismatch",)


def test_recovery_truth_is_distinct_from_original_payment_truth() -> None:
    active = resolve_payment_truth(
        (fact("ev_active", "recovery.status", "executing"),),
        resolved_at=NOW,
    )
    recovered = resolve_payment_truth(
        (fact("ev_recovered", "recovery.status", "verified"),),
        resolved_at=NOW,
    )

    assert active.state is PaymentTruthState.RECOVERY_ALREADY_ACTIVE
    assert recovered.state is PaymentTruthState.RECOVERY_CONFIRMED


def test_pending_and_unknown_are_not_treated_as_failure() -> None:
    pending = resolve_payment_truth(
        (fact("ev_pending", "payment.status", "created"),),
        resolved_at=NOW,
    )
    unknown = resolve_payment_truth((), resolved_at=NOW)

    assert pending.state is PaymentTruthState.PAYMENT_PENDING
    assert unknown.state is PaymentTruthState.OUTCOME_UNKNOWN


def test_evidence_requires_a_valid_sha256_digest() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        PaymentTruthEvidenceFact(
            evidence_id="ev_invalid",
            source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
            fact_name="payment.status",
            fact_value="failed",
            content_sha256="not-a-digest",
            observed_at=NOW,
            verified=True,
        )
