from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeProof,
    RecoveryOutcomeStatus,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
PAYMENT_ATTEMPT_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")


def build_recovered_proof(
    **changes: object,
) -> RecoveryOutcomeProof:
    values: dict[str, object] = {
        "recovery_case_id": CASE_ID,
        "payment_attempt_id": PAYMENT_ATTEMPT_ID,
        "provider_payment_id": "pay_rr_outcome_001",
        "status": RecoveryOutcomeStatus.RECOVERED,
        "attribution": RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
        "occurred_at": NOW,
        "original_amount_minor": 45_000,
        "currency": "inr",
        "recovery_action_id": ACTION_ID,
        "payment_link_id": "plink_rr_outcome_001",
        "provider_outcome_id": "pay_rr_recovered_001",
        "gross_recovered_minor": 45_000,
        "evidence_event_ids": ("evt_rr_payment_link_paid_001",),
    }
    values.update(changes)

    return RecoveryOutcomeProof(**values)


def test_recovered_proof_normalizes_identifiers_and_currency() -> None:
    proof = build_recovered_proof(
        provider_payment_id="  pay_rr_outcome_001  ",
        currency=" inr ",
        payment_link_id="  plink_rr_outcome_001  ",
        provider_outcome_id="  pay_rr_recovered_001  ",
        evidence_event_ids=("  evt_rr_payment_link_paid_001  ",),
    )

    assert proof.provider_payment_id == "pay_rr_outcome_001"
    assert proof.currency == "INR"
    assert proof.payment_link_id == "plink_rr_outcome_001"
    assert proof.provider_outcome_id == "pay_rr_recovered_001"
    assert proof.evidence_event_ids == ("evt_rr_payment_link_paid_001",)


def test_recovered_proof_reports_net_recovery() -> None:
    proof = build_recovered_proof(
        gross_recovered_minor=45_000,
        reversed_minor=5_000,
    )

    assert proof.net_recovered_minor == 40_000
    assert proof.has_recovered_revenue is True


def test_recovered_proof_rejects_naive_timestamp() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        build_recovered_proof(
            occurred_at=datetime(2026, 8, 25, 12, 0),
        )


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        (
            "original_amount_minor",
            0,
            "Original payment amount must be positive",
        ),
        (
            "gross_recovered_minor",
            -1,
            "Gross recovered amount cannot be negative",
        ),
        (
            "reversed_minor",
            -1,
            "Reversed amount cannot be negative",
        ),
        (
            "duplicate_collection_prevented_minor",
            -1,
            "Duplicate collection prevented amount cannot be negative",
        ),
    ],
)
def test_recovered_proof_rejects_invalid_money_values(
    field_name: str,
    value: int,
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        build_recovered_proof(
            **{field_name: value},
        )


def test_recovered_proof_rejects_amount_above_original_payment() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed original payment amount",
    ):
        build_recovered_proof(
            gross_recovered_minor=45_001,
        )


def test_recovered_proof_rejects_reversal_above_recovered_amount() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed recovered amount",
    ):
        build_recovered_proof(
            reversed_minor=45_001,
        )


def test_recovered_outcome_requires_direct_link_attribution_and_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="direct Payment Link attribution",
    ):
        build_recovered_proof(
            attribution=RecoveryOutcomeAttribution.NONE,
        )

    with pytest.raises(
        ValueError,
        match="action, Payment Link, and evidence",
    ):
        build_recovered_proof(
            payment_link_id=None,
        )


def test_duplicate_collection_prevention_is_not_counted_as_recovered_revenue() -> None:
    proof = RecoveryOutcomeProof(
        recovery_case_id=CASE_ID,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        provider_payment_id="pay_rr_outcome_001",
        status=RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED,
        attribution=(RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY),
        occurred_at=NOW,
        original_amount_minor=45_000,
        currency="INR",
        recovery_action_id=ACTION_ID,
        payment_link_id="plink_rr_outcome_001",
        duplicate_collection_prevented_minor=45_000,
        evidence_event_ids=(
            "evt_rr_late_authorization_001",
            "evt_rr_payment_link_cancelled_001",
        ),
    )

    assert proof.net_recovered_minor == 0
    assert proof.has_recovered_revenue is False
    assert proof.duplicate_collection_prevented_minor == 45_000


def test_duplicate_prevention_requires_safety_attribution_and_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="late-authorization safety attribution",
    ):
        RecoveryOutcomeProof(
            recovery_case_id=CASE_ID,
            payment_attempt_id=PAYMENT_ATTEMPT_ID,
            provider_payment_id="pay_rr_outcome_001",
            status=RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED,
            attribution=RecoveryOutcomeAttribution.NONE,
            occurred_at=NOW,
            original_amount_minor=45_000,
            currency="INR",
            duplicate_collection_prevented_minor=45_000,
            evidence_event_ids=("evt_rr_late_authorization_001",),
        )

    with pytest.raises(
        ValueError,
        match="requires evidence",
    ):
        RecoveryOutcomeProof(
            recovery_case_id=CASE_ID,
            payment_attempt_id=PAYMENT_ATTEMPT_ID,
            provider_payment_id="pay_rr_outcome_001",
            status=RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED,
            attribution=(RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY),
            occurred_at=NOW,
            original_amount_minor=45_000,
            currency="INR",
            duplicate_collection_prevented_minor=45_000,
        )


def test_zero_impact_outcome_cannot_claim_revenue() -> None:
    with pytest.raises(
        ValueError,
        match="Zero-impact outcome cannot contain financial impact amounts",
    ):
        RecoveryOutcomeProof(
            recovery_case_id=CASE_ID,
            payment_attempt_id=PAYMENT_ATTEMPT_ID,
            provider_payment_id="pay_rr_outcome_001",
            status=RecoveryOutcomeStatus.PAYMENT_LINK_PENDING,
            attribution=RecoveryOutcomeAttribution.NONE,
            occurred_at=NOW,
            original_amount_minor=45_000,
            currency="INR",
            gross_recovered_minor=1,
        )


def test_zero_impact_outcome_requires_no_attribution() -> None:
    with pytest.raises(
        ValueError,
        match="requires no revenue attribution",
    ):
        RecoveryOutcomeProof(
            recovery_case_id=CASE_ID,
            payment_attempt_id=PAYMENT_ATTEMPT_ID,
            provider_payment_id="pay_rr_outcome_001",
            status=RecoveryOutcomeStatus.PAYMENT_LINK_CANCELLED,
            attribution=RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
            occurred_at=NOW,
            original_amount_minor=45_000,
            currency="INR",
        )


def test_reversed_outcome_requires_recovery_and_reversal_evidence() -> None:
    proof = build_recovered_proof(
        status=RecoveryOutcomeStatus.REVERSED,
        reversed_minor=45_000,
    )

    assert proof.net_recovered_minor == 0
    assert proof.has_recovered_revenue is False

    with pytest.raises(
        ValueError,
        match="requires recovered and reversed amounts",
    ):
        build_recovered_proof(
            status=RecoveryOutcomeStatus.REVERSED,
            gross_recovered_minor=0,
            reversed_minor=0,
        )


def test_evidence_event_ids_must_be_unique() -> None:
    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        build_recovered_proof(
            evidence_event_ids=(
                "evt_rr_payment_link_paid_001",
                "evt_rr_payment_link_paid_001",
            ),
        )
