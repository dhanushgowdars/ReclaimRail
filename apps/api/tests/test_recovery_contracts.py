from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.recovery.contracts import (
    AIClaim,
    ApprovalGrant,
    InvestigationHypothesis,
    InvestigationHypothesisStatus,
    PaymentEvidence,
    PaymentEvidenceSource,
    PaymentTruthSnapshot,
    PaymentTruthState,
    ProviderActionAttempt,
    ProviderActionStatus,
    RecoveryIntent,
    RecoveryIntentAction,
    RecoveryReceipt,
)

NOW = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)
DIGEST = "a" * 64


def test_payment_evidence_normalizes_and_validates_identity() -> None:
    evidence = PaymentEvidence(
        evidence_id=" ev_102 ",
        case_id=uuid4(),
        source=PaymentEvidenceSource.PROVIDER_PAYMENT_API,
        fact_name=" payment.status ",
        fact_value=" captured ",
        observed_at=NOW,
        content_sha256=DIGEST.upper(),
        fresh_until=NOW + timedelta(minutes=5),
        verified=True,
    )

    assert evidence.evidence_id == "ev_102"
    assert evidence.fact_name == "payment.status"
    assert evidence.fact_value == "captured"
    assert evidence.content_sha256 == DIGEST


@pytest.mark.parametrize(
    ("observed_at", "digest"),
    [
        (datetime(2026, 9, 22, 10, 30), DIGEST),
        (NOW, "not-a-digest"),
    ],
)
def test_payment_evidence_rejects_unverifiable_contract_values(
    observed_at: datetime,
    digest: str,
) -> None:
    with pytest.raises(ValueError):
        PaymentEvidence(
            evidence_id="ev_1",
            case_id=uuid4(),
            source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
            fact_name="payment.status",
            fact_value="failed",
            observed_at=observed_at,
            content_sha256=digest,
        )


def test_source_conflict_truth_requires_a_closed_conflict_code() -> None:
    with pytest.raises(ValueError, match="conflict code"):
        PaymentTruthSnapshot(
            case_id=uuid4(),
            version=1,
            state=PaymentTruthState.SOURCE_CONFLICT,
            evidence_refs=("ev_provider", "ev_merchant"),
            resolved_at=NOW,
        )


def test_non_conflict_truth_rejects_conflict_codes() -> None:
    with pytest.raises(ValueError, match="only for source-conflict"):
        PaymentTruthSnapshot(
            case_id=uuid4(),
            version=1,
            state=PaymentTruthState.PAYMENT_CONFIRMED,
            evidence_refs=("ev_provider",),
            conflict_codes=("provider_merchant_mismatch",),
            resolved_at=NOW,
        )


def test_ai_claim_cannot_exist_without_evidence() -> None:
    with pytest.raises(ValueError, match="evidence references"):
        AIClaim(
            claim_id="claim_1",
            statement="The provider captured the original payment",
            evidence_refs=(),
        )


def test_confirmed_and_rejected_hypotheses_require_proof() -> None:
    with pytest.raises(ValueError, match="supporting evidence"):
        InvestigationHypothesis(
            hypothesis_id="hyp_1",
            statement="Original payment was captured after a client timeout",
            status=InvestigationHypothesisStatus.CONFIRMED,
        )

    with pytest.raises(ValueError, match="contradicting evidence"):
        InvestigationHypothesis(
            hypothesis_id="hyp_2",
            statement="The issuer permanently declined the payment",
            status=InvestigationHypothesisStatus.REJECTED,
        )


def test_recovery_intent_contains_references_not_money_or_customer_coordinates() -> None:
    intent = RecoveryIntent(
        intent_id=uuid4(),
        case_id=uuid4(),
        case_version=4,
        truth_version=3,
        action=RecoveryIntentAction.CREATE_PAYMENT_LINK,
        evidence_refs=("ev_1", "ev_1", "ev_2"),
        rationale_claim_ids=("claim_1",),
        proposed_at=NOW,
    )

    assert intent.evidence_refs == ("ev_1", "ev_2")
    assert not hasattr(intent, "amount_minor")
    assert not hasattr(intent, "customer_email")
    assert not hasattr(intent, "provider_url")


def test_approval_is_versioned_amount_bound_and_time_bound() -> None:
    approval = ApprovalGrant(
        approval_id=uuid4(),
        case_id=uuid4(),
        case_version=4,
        truth_version=3,
        action=RecoveryIntentAction.CREATE_PAYMENT_LINK,
        amount_minor=349900,
        evidence_digest=DIGEST,
        granted_by="operator-17",
        granted_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    assert approval.amount_minor == 349900
    assert approval.expires_at > approval.granted_at


def test_approval_rejects_non_positive_amount_and_non_future_expiry() -> None:
    with pytest.raises(ValueError, match="amount"):
        ApprovalGrant(
            approval_id=uuid4(),
            case_id=uuid4(),
            case_version=1,
            truth_version=1,
            action=RecoveryIntentAction.CREATE_PAYMENT_LINK,
            amount_minor=0,
            evidence_digest=DIGEST,
            granted_by="operator-17",
            granted_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )

    with pytest.raises(ValueError, match="expiry"):
        ApprovalGrant(
            approval_id=uuid4(),
            case_id=uuid4(),
            case_version=1,
            truth_version=1,
            action=RecoveryIntentAction.CREATE_PAYMENT_LINK,
            amount_minor=349900,
            evidence_digest=DIGEST,
            granted_by="operator-17",
            granted_at=NOW,
            expires_at=NOW,
        )


def test_verified_provider_action_requires_provider_reference() -> None:
    with pytest.raises(ValueError, match="provider reference"):
        ProviderActionAttempt(
            attempt_id=uuid4(),
            intent_id=uuid4(),
            idempotency_key="b" * 64,
            status=ProviderActionStatus.VERIFIED,
            created_at=NOW,
        )


def test_recovery_receipt_binds_truth_evidence_decision_and_chain() -> None:
    receipt = RecoveryReceipt(
        receipt_id=uuid4(),
        case_id=uuid4(),
        truth_version=3,
        evidence_digest="a" * 64,
        decision_digest="b" * 64,
        previous_receipt_hash="c" * 64,
        receipt_hash="d" * 64,
        created_at=NOW,
        action_attempt_id=uuid4(),
    )

    assert receipt.truth_version == 3
    assert receipt.previous_receipt_hash == "c" * 64
