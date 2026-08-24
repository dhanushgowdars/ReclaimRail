from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.payments import PaymentState
from app.domain.recovery import (
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryGuardrail,
    RecoveryPolicyDecision,
    RecoveryPolicyOutcome,
)

NOW = datetime(
    2026,
    8,
    24,
    12,
    0,
    tzinfo=UTC,
)


def create_snapshot(
    **overrides: object,
) -> RecoveryCaseSnapshot:
    values: dict[str, object] = {
        "case_id": uuid4(),
        "payment_attempt_id": uuid4(),
        "provider_payment_id": "pay_test_123",
        "payment_state": PaymentState.FAILED,
        "amount_minor": 100_000,
        "currency": "INR",
        "payment_method": "upi",
        "status": RecoveryCaseStatus.OPEN,
        "recovery_attempt_count": 0,
        "customer_contact_allowed": True,
    }
    values.update(overrides)

    return RecoveryCaseSnapshot(**values)  # type: ignore[arg-type]


def test_normalizes_recovery_case_identifiers() -> None:
    snapshot = create_snapshot(
        provider_payment_id="  pay_test_123  ",
        currency="inr",
        payment_method="  UPI  ",
        active_payment_link_id="  plink_123  ",
    )

    assert snapshot.provider_payment_id == "pay_test_123"
    assert snapshot.currency == "INR"
    assert snapshot.payment_method == "upi"
    assert snapshot.active_payment_link_id == "plink_123"


def test_rejects_nonpositive_payment_amount() -> None:
    with pytest.raises(
        ValueError,
        match="must be positive",
    ):
        create_snapshot(amount_minor=0)


def test_rejects_negative_recovery_attempt_count() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        create_snapshot(recovery_attempt_count=-1)


def test_requires_timezone_aware_snapshot_timestamps() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        create_snapshot(
            last_customer_contact_at=datetime(
                2026,
                8,
                24,
                12,
                0,
            ),
        )


def test_recovered_case_requires_timestamp() -> None:
    with pytest.raises(
        ValueError,
        match="requires recovery timestamp",
    ):
        create_snapshot(
            status=RecoveryCaseStatus.RECOVERED,
        )

    snapshot = create_snapshot(
        status=RecoveryCaseStatus.RECOVERED,
        recovered_at=NOW,
    )

    assert snapshot.recovered_at == NOW


def test_payment_link_requires_amount_and_currency() -> None:
    with pytest.raises(
        ValueError,
        match="requires amount and currency",
    ):
        RecoveryActionProposal(
            action_type=(RecoveryActionType.CREATE_PAYMENT_LINK),
            reason="Create a bounded recovery link",
        )

    proposal = RecoveryActionProposal(
        action_type=(RecoveryActionType.CREATE_PAYMENT_LINK),
        reason="Create a bounded recovery link",
        amount_minor=100_000,
        currency="inr",
    )

    assert proposal.currency == "INR"


def test_customer_contact_requires_channel() -> None:
    with pytest.raises(
        ValueError,
        match="requires a channel",
    ):
        RecoveryActionProposal(
            action_type=(RecoveryActionType.SEND_RECOVERY_MESSAGE),
            reason="Send a recovery reminder",
        )

    proposal = RecoveryActionProposal(
        action_type=(RecoveryActionType.SEND_RECOVERY_MESSAGE),
        reason="Send a recovery reminder",
        channel=RecoveryChannel.EMAIL,
    )

    assert proposal.channel is RecoveryChannel.EMAIL


def test_wait_requires_timezone_aware_execution_time() -> None:
    with pytest.raises(
        ValueError,
        match="requires execution time",
    ):
        RecoveryActionProposal(
            action_type=RecoveryActionType.WAIT,
            reason="Respect the quiet period",
        )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        RecoveryActionProposal(
            action_type=RecoveryActionType.WAIT,
            reason="Respect the quiet period",
            execute_after=datetime(2026, 8, 24, 16, 0),
        )

    proposal = RecoveryActionProposal(
        action_type=RecoveryActionType.WAIT,
        reason="Respect the quiet period",
        execute_after=NOW + timedelta(hours=4),
    )

    assert proposal.execute_after == (NOW + timedelta(hours=4))


def test_policy_decision_enforces_guardrail_evidence() -> None:
    allowed = RecoveryPolicyDecision(
        outcome=RecoveryPolicyOutcome.ALLOW,
        guardrails=(),
        explanation="All deterministic checks passed",
        evaluated_at=NOW,
    )

    assert allowed.guardrails == ()

    with pytest.raises(
        ValueError,
        match="cannot contain",
    ):
        RecoveryPolicyDecision(
            outcome=RecoveryPolicyOutcome.ALLOW,
            guardrails=(RecoveryGuardrail.QUIET_PERIOD_ACTIVE,),
            explanation="Invalid allowed decision",
            evaluated_at=NOW,
        )

    with pytest.raises(
        ValueError,
        match="requires guardrail evidence",
    ):
        RecoveryPolicyDecision(
            outcome=RecoveryPolicyOutcome.BLOCK,
            guardrails=(),
            explanation="Invalid blocked decision",
            evaluated_at=NOW,
        )
