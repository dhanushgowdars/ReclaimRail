from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain.recovery.outcome_classifier import (
    RecoveryOutcomeReconciliationInput,
    RecoveryPaymentLinkOutcomeState,
    reconcile_recovery_outcome,
)
from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeStatus,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
LATE_AUTHORIZATION_AT = datetime(2026, 8, 25, 11, 59, tzinfo=UTC)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
PAYMENT_ATTEMPT_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")


def build_input(
    **changes: object,
) -> RecoveryOutcomeReconciliationInput:
    values: dict[str, object] = {
        "recovery_case_id": CASE_ID,
        "payment_attempt_id": PAYMENT_ATTEMPT_ID,
        "recovery_action_id": ACTION_ID,
        "provider_payment_id": "pay_rr_reconcile_001",
        "payment_link_id": "plink_rr_reconcile_001",
        "original_amount_minor": 45_000,
        "currency": "INR",
        "payment_link_state": (RecoveryPaymentLinkOutcomeState.PENDING),
        "observed_at": NOW,
        "evidence_event_ids": ("evt_rr_reconcile_001",),
    }
    values.update(changes)

    return RecoveryOutcomeReconciliationInput(**values)


def test_input_normalizes_identifiers_and_currency() -> None:
    value = build_input(
        provider_payment_id="  pay_rr_reconcile_001  ",
        payment_link_id="  plink_rr_reconcile_001  ",
        currency=" inr ",
        evidence_event_ids=("  evt_rr_reconcile_001  ",),
    )

    assert value.provider_payment_id == "pay_rr_reconcile_001"
    assert value.payment_link_id == "plink_rr_reconcile_001"
    assert value.currency == "INR"
    assert value.evidence_event_ids == ("evt_rr_reconcile_001",)


def test_input_rejects_naive_timestamps() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        build_input(
            observed_at=datetime(2026, 8, 25, 12, 0),
        )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        build_input(
            late_authorization_detected_at=datetime(
                2026,
                8,
                25,
                11,
                59,
            ),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"original_amount_minor": 0},
            "Original payment amount must be positive",
        ),
        (
            {"payment_link_paid_amount_minor": -1},
            "Payment Link paid amount cannot be negative",
        ),
        (
            {"payment_link_reversed_minor": -1},
            "Payment Link reversed amount cannot be negative",
        ),
        (
            {
                "payment_link_paid_amount_minor": 45_001,
            },
            "cannot exceed original payment amount",
        ),
        (
            {
                "payment_link_paid_amount_minor": 10_000,
                "payment_link_reversed_minor": 10_001,
            },
            "cannot exceed Payment Link paid amount",
        ),
    ],
)
def test_input_rejects_invalid_monetary_values(
    changes: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        build_input(**changes)


def test_paid_link_requires_positive_paid_amount() -> None:
    with pytest.raises(
        ValueError,
        match="requires a positive paid amount",
    ):
        build_input(
            payment_link_state=RecoveryPaymentLinkOutcomeState.PAID,
        )


def test_unpaid_link_state_rejects_paid_amounts() -> None:
    with pytest.raises(
        ValueError,
        match="Unpaid Payment Link state cannot contain paid amounts",
    ):
        build_input(
            payment_link_state=RecoveryPaymentLinkOutcomeState.EXPIRED,
            payment_link_paid_amount_minor=45_000,
        )


def test_reversed_link_requires_paid_and_reversed_amounts() -> None:
    with pytest.raises(
        ValueError,
        match="requires paid and reversed amounts",
    ):
        build_input(
            payment_link_state=RecoveryPaymentLinkOutcomeState.REVERSED,
            payment_link_paid_amount_minor=45_000,
        )


def test_paid_payment_link_becomes_direct_recovered_revenue() -> None:
    proof = reconcile_recovery_outcome(
        build_input(
            payment_link_state=RecoveryPaymentLinkOutcomeState.PAID,
            payment_link_paid_amount_minor=45_000,
        ),
    )

    assert proof.status is RecoveryOutcomeStatus.RECOVERED
    assert proof.attribution is (RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK)
    assert proof.gross_recovered_minor == 45_000
    assert proof.net_recovered_minor == 45_000
    assert proof.has_recovered_revenue is True


def test_reversed_payment_link_reduces_net_recovered_revenue() -> None:
    proof = reconcile_recovery_outcome(
        build_input(
            payment_link_state=RecoveryPaymentLinkOutcomeState.REVERSED,
            payment_link_paid_amount_minor=45_000,
            payment_link_reversed_minor=45_000,
        ),
    )

    assert proof.status is RecoveryOutcomeStatus.REVERSED
    assert proof.gross_recovered_minor == 45_000
    assert proof.reversed_minor == 45_000
    assert proof.net_recovered_minor == 0
    assert proof.has_recovered_revenue is False


@pytest.mark.parametrize(
    ("link_state", "expected_status"),
    [
        (
            RecoveryPaymentLinkOutcomeState.PENDING,
            RecoveryOutcomeStatus.PAYMENT_LINK_PENDING,
        ),
        (
            RecoveryPaymentLinkOutcomeState.EXPIRED,
            RecoveryOutcomeStatus.PAYMENT_LINK_EXPIRED,
        ),
        (
            RecoveryPaymentLinkOutcomeState.CANCELLED,
            RecoveryOutcomeStatus.PAYMENT_LINK_CANCELLED,
        ),
    ],
)
def test_unpaid_link_states_have_zero_revenue_attribution(
    link_state: RecoveryPaymentLinkOutcomeState,
    expected_status: RecoveryOutcomeStatus,
) -> None:
    proof = reconcile_recovery_outcome(
        build_input(
            payment_link_state=link_state,
        ),
    )

    assert proof.status is expected_status
    assert proof.attribution is RecoveryOutcomeAttribution.NONE
    assert proof.net_recovered_minor == 0
    assert proof.duplicate_collection_prevented_minor == 0


def test_late_authorization_and_cancelled_link_prevents_duplicate_collection() -> None:
    proof = reconcile_recovery_outcome(
        build_input(
            payment_link_state=RecoveryPaymentLinkOutcomeState.CANCELLED,
            late_authorization_detected_at=LATE_AUTHORIZATION_AT,
            evidence_event_ids=(
                "evt_rr_late_authorization_001",
                "evt_rr_payment_link_cancelled_001",
            ),
        ),
    )

    assert proof.status is (RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED)
    assert proof.attribution is (RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY)
    assert proof.net_recovered_minor == 0
    assert proof.duplicate_collection_prevented_minor == 45_000


@pytest.mark.parametrize(
    "link_state",
    [
        RecoveryPaymentLinkOutcomeState.PENDING,
        RecoveryPaymentLinkOutcomeState.PAID,
        RecoveryPaymentLinkOutcomeState.EXPIRED,
        RecoveryPaymentLinkOutcomeState.REVERSED,
    ],
)
def test_late_authorization_without_confirmed_link_cancellation_stays_unresolved(
    link_state: RecoveryPaymentLinkOutcomeState,
) -> None:
    changes: dict[str, object] = {
        "payment_link_state": link_state,
        "late_authorization_detected_at": LATE_AUTHORIZATION_AT,
    }

    if link_state is RecoveryPaymentLinkOutcomeState.PAID:
        changes["payment_link_paid_amount_minor"] = 45_000
    elif link_state is RecoveryPaymentLinkOutcomeState.REVERSED:
        changes["payment_link_paid_amount_minor"] = 45_000
        changes["payment_link_reversed_minor"] = 45_000

    proof = reconcile_recovery_outcome(
        build_input(**changes),
    )

    assert proof.status is RecoveryOutcomeStatus.UNRESOLVED
    assert proof.attribution is RecoveryOutcomeAttribution.NONE
    assert proof.net_recovered_minor == 0
    assert proof.duplicate_collection_prevented_minor == 0


def test_input_requires_unique_nonempty_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="requires evidence event IDs",
    ):
        build_input(
            evidence_event_ids=(),
        )

    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        build_input(
            evidence_event_ids=(
                "evt_rr_reconcile_001",
                "evt_rr_reconcile_001",
            ),
        )
