from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeStatus,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkStatus,
)
from app.services.recovery_outcome_reconciler import (
    PreparedRecoveryOutcomeReconciliation,
    RecoveryOutcomeProviderEvidenceError,
    _build_outcome_proof,
    _mark_case_closed_without_recovery,
    _provider_observed_at,
    _validate_provider_payment_link,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
PAYMENT_ATTEMPT_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")

RECONCILED_AT = datetime(
    2026,
    8,
    25,
    16,
    0,
    tzinfo=UTC,
)
PROVIDER_UPDATED_AT = 1_787_635_200


def build_prepared() -> PreparedRecoveryOutcomeReconciliation:
    return PreparedRecoveryOutcomeReconciliation(
        recovery_case_id=CASE_ID,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        recovery_action_id=ACTION_ID,
        provider_payment_id="pay_reconciliation_001",
        payment_link_id="plink_reconciliation_001",
        reference_id=f"rr_{ACTION_ID.hex}",
        original_amount_minor=349_900,
        currency="INR",
    )


def build_payment_link(
    *,
    status: RazorpayPaymentLinkStatus,
    amount_paid_minor: int = 0,
    payment_link_id: str = "plink_reconciliation_001",
    reference_id: str | None = None,
    amount_minor: int = 349_900,
    currency: str = "INR",
    provider_updated_at: int | None = PROVIDER_UPDATED_AT,
) -> RazorpayPaymentLink:
    return RazorpayPaymentLink.model_validate(
        {
            "id": payment_link_id,
            "short_url": "https://rzp.io/i/recovery-test",
            "status": status.value,
            "amount": amount_minor,
            "amount_paid": amount_paid_minor,
            "currency": currency,
            "reference_id": reference_id or f"rr_{ACTION_ID.hex}",
            "updated_at": provider_updated_at,
        },
    )


def build_recovery_case(
    *,
    late_authorization_detected_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        late_authorization_detected_at=late_authorization_detected_at,
    )


def build_payment_attempt(
    *,
    late_authorization_detected_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        late_authorization_detected_at=late_authorization_detected_at,
    )


def test_paid_payment_link_becomes_verified_recovered_outcome() -> None:
    proof = _build_outcome_proof(
        prepared=build_prepared(),
        recovery_case=build_recovery_case(),
        payment_attempt=build_payment_attempt(),
        payment_link=build_payment_link(
            status=RazorpayPaymentLinkStatus.PAID,
            amount_paid_minor=349_900,
        ),
        reconciled_at=RECONCILED_AT,
    )

    assert proof.status is RecoveryOutcomeStatus.RECOVERED
    assert proof.attribution is RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK
    assert proof.gross_recovered_minor == 349_900
    assert proof.reversed_minor == 0
    assert proof.duplicate_collection_prevented_minor == 0
    assert proof.payment_link_id == "plink_reconciliation_001"
    assert proof.evidence_event_ids == (
        (
            "razorpay:payment_link:plink_reconciliation_001:"
            f"status:paid:amount_paid:349900:updated_at:{PROVIDER_UPDATED_AT}"
        ),
    )


def test_cancelled_link_after_late_authorization_prevents_duplicate() -> None:
    late_authorization_at = datetime(
        2026,
        8,
        25,
        15,
        55,
        tzinfo=UTC,
    )

    proof = _build_outcome_proof(
        prepared=build_prepared(),
        recovery_case=build_recovery_case(
            late_authorization_detected_at=late_authorization_at,
        ),
        payment_attempt=build_payment_attempt(
            late_authorization_detected_at=late_authorization_at,
        ),
        payment_link=build_payment_link(
            status=RazorpayPaymentLinkStatus.CANCELLED,
        ),
        reconciled_at=RECONCILED_AT,
    )

    assert proof.status is RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED
    assert proof.attribution is RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY
    assert proof.gross_recovered_minor == 0
    assert proof.duplicate_collection_prevented_minor == 349_900


def test_partially_paid_link_is_not_counted_as_recovered_revenue() -> None:
    proof = _build_outcome_proof(
        prepared=build_prepared(),
        recovery_case=build_recovery_case(),
        payment_attempt=build_payment_attempt(),
        payment_link=build_payment_link(
            status=RazorpayPaymentLinkStatus.PARTIALLY_PAID,
            amount_paid_minor=100_000,
        ),
        reconciled_at=RECONCILED_AT,
    )

    assert proof.status is RecoveryOutcomeStatus.UNRESOLVED
    assert proof.attribution is RecoveryOutcomeAttribution.NONE
    assert proof.gross_recovered_minor == 0
    assert proof.duplicate_collection_prevented_minor == 0


def test_created_link_remains_pending() -> None:
    proof = _build_outcome_proof(
        prepared=build_prepared(),
        recovery_case=build_recovery_case(),
        payment_attempt=build_payment_attempt(),
        payment_link=build_payment_link(
            status=RazorpayPaymentLinkStatus.CREATED,
        ),
        reconciled_at=RECONCILED_AT,
    )

    assert proof.status is RecoveryOutcomeStatus.PAYMENT_LINK_PENDING
    assert proof.attribution is RecoveryOutcomeAttribution.NONE
    assert proof.gross_recovered_minor == 0


@pytest.mark.parametrize(
    ("outcome_status", "close_reason"),
    [
        (
            RecoveryOutcomeStatus.PAYMENT_LINK_EXPIRED,
            "payment_link_expired_without_recovery",
        ),
        (
            RecoveryOutcomeStatus.PAYMENT_LINK_CANCELLED,
            "payment_link_cancelled_without_recovery",
        ),
        (
            RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED,
            "duplicate_collection_prevented",
        ),
    ],
)
def test_terminal_provider_outcome_closes_case_without_recovery(
    outcome_status: RecoveryOutcomeStatus,
    close_reason: str,
) -> None:
    recovery_case = SimpleNamespace(
        status="waiting",
        closed_at=None,
        close_reason=None,
        active_payment_link_id="plink_reconciliation_001",
        next_action_at=RECONCILED_AT,
        version=3,
    )

    changed = _mark_case_closed_without_recovery(
        recovery_case=recovery_case,
        outcome_status=outcome_status,
        closed_at=RECONCILED_AT,
    )

    assert changed is True
    assert recovery_case.status == "cancelled"
    assert recovery_case.closed_at == RECONCILED_AT
    assert recovery_case.close_reason == close_reason
    assert recovery_case.active_payment_link_id is None
    assert recovery_case.next_action_at is None
    assert recovery_case.version == 4


def test_paid_link_with_zero_amount_is_rejected_as_invalid_evidence() -> None:
    with pytest.raises(
        RecoveryOutcomeProviderEvidenceError,
        match="zero paid amount",
    ):
        _build_outcome_proof(
            prepared=build_prepared(),
            recovery_case=build_recovery_case(),
            payment_attempt=build_payment_attempt(),
            payment_link=build_payment_link(
                status=RazorpayPaymentLinkStatus.PAID,
                amount_paid_minor=0,
            ),
            reconciled_at=RECONCILED_AT,
        )


def test_rejects_provider_link_with_unexpected_reference() -> None:
    with pytest.raises(
        RecoveryOutcomeProviderEvidenceError,
        match="reference",
    ):
        _validate_provider_payment_link(
            prepared=build_prepared(),
            payment_link=build_payment_link(
                status=RazorpayPaymentLinkStatus.CREATED,
                reference_id="rr_wrong_reference",
            ),
        )


def test_falls_back_to_reconciliation_time_without_provider_timestamp() -> None:
    observed_at = _provider_observed_at(
        payment_link=build_payment_link(
            status=RazorpayPaymentLinkStatus.CREATED,
            provider_updated_at=None,
        ),
        reconciled_at=RECONCILED_AT,
    )

    assert observed_at == RECONCILED_AT
