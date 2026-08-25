from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import RecoveryAuditEvent, RecoveryCase
from app.domain.payments import PaymentState
from app.services import recovery_case_service
from app.services.recovery_case_service import (
    PaymentAttemptNotFoundError,
    RecoveryCaseCreationDisposition,
    RecoveryCaseIneligibilityReason,
    create_or_get_recovery_case,
    evaluate_recovery_case_eligibility,
)

PAYMENT_ATTEMPT_ID = UUID("10000000-0000-0000-0000-000000000001")
RECOVERY_CASE_ID = UUID("20000000-0000-0000-0000-000000000001")
AUDIT_EVENT_ID = UUID("30000000-0000-0000-0000-000000000001")
OPENED_AT = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)


def query_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def create_payment_attempt(
    *,
    state: PaymentState = PaymentState.FAILED,
    recovery_eligible: bool = True,
    recovery_stopped: bool = False,
    amount_minor: int = 149_900,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=PAYMENT_ATTEMPT_ID,
        provider="razorpay",
        provider_payment_id="pay_recovery_case_test",
        amount_minor=amount_minor,
        currency="inr",
        method=" UPI ",
        payment_created_at=OPENED_AT,
        current_state=state.value,
        state_version=1,
        state_provider_event_id="evt_recovery_case_test",
        state_webhook_event_id=UUID("40000000-0000-0000-0000-000000000001"),
        state_event_created_at=OPENED_AT,
        recovery_eligible=recovery_eligible,
        recovery_stopped_at=(OPENED_AT if recovery_stopped else None),
        recovery_stop_reason=("late_authorization" if recovery_stopped else None),
    )


def create_audit_event() -> RecoveryAuditEvent:
    return RecoveryAuditEvent(
        id=AUDIT_EVENT_ID,
        recovery_case_id=RECOVERY_CASE_ID,
        sequence_number=1,
        event_type="case.opened",
        actor_type="system",
        event_data={},
        previous_event_hash=None,
        event_hash="a" * 64,
        hash_algorithm="sha256",
        occurred_at=OPENED_AT,
    )


def test_eligible_failed_payment_has_no_reasons() -> None:
    assert evaluate_recovery_case_eligibility(create_payment_attempt()) == ()


def test_eligibility_returns_all_guardrail_reasons() -> None:
    payment_attempt = create_payment_attempt(
        state=PaymentState.AUTHORIZED,
        recovery_eligible=False,
        recovery_stopped=True,
        amount_minor=0,
    )

    assert evaluate_recovery_case_eligibility(payment_attempt) == (
        RecoveryCaseIneligibilityReason.PAYMENT_NOT_FAILED,
        RecoveryCaseIneligibilityReason.RECOVERY_NOT_ELIGIBLE,
        RecoveryCaseIneligibilityReason.RECOVERY_ALREADY_STOPPED,
        RecoveryCaseIneligibilityReason.NONPOSITIVE_AMOUNT,
    )


@pytest.mark.asyncio
async def test_creates_case_and_genesis_audit_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_attempt = create_payment_attempt()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(payment_attempt),
        query_result(None),
    ]
    audit_event = create_audit_event()
    append_audit = AsyncMock(return_value=audit_event)
    monkeypatch.setattr(
        recovery_case_service,
        "append_recovery_audit_event",
        append_audit,
    )

    result = await create_or_get_recovery_case(
        session,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        opened_at=OPENED_AT,
        customer_contact_allowed=True,
    )

    assert result.disposition is RecoveryCaseCreationDisposition.CREATED
    assert result.recovery_case is not None
    assert result.recovery_case.payment_attempt_id == PAYMENT_ATTEMPT_ID
    assert result.recovery_case.amount_minor == 149_900
    assert result.recovery_case.currency == "INR"
    assert result.recovery_case.payment_method == "upi"
    assert result.recovery_case.customer_contact_allowed is True
    assert result.audit_event is audit_event
    assert result.ineligibility_reasons == ()
    session.add.assert_called_once_with(result.recovery_case)
    session.flush.assert_awaited_once_with()
    append_audit.assert_awaited_once()

    append_request = append_audit.await_args.kwargs["request"]
    assert append_request.event_type == "case.opened"
    assert append_request.event_data["payment_state"] == "failed"
    assert append_request.event_data["amount_minor"] == 149_900


@pytest.mark.asyncio
async def test_replay_returns_existing_case_without_new_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_attempt = create_payment_attempt()
    existing_case = RecoveryCase(
        id=RECOVERY_CASE_ID,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        status="open",
        amount_minor=149_900,
        currency="INR",
        payment_method="upi",
        customer_contact_allowed=True,
        opened_at=OPENED_AT,
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(payment_attempt),
        query_result(existing_case),
    ]
    append_audit = AsyncMock()
    monkeypatch.setattr(
        recovery_case_service,
        "append_recovery_audit_event",
        append_audit,
    )

    result = await create_or_get_recovery_case(
        session,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        opened_at=OPENED_AT,
        customer_contact_allowed=True,
    )

    assert result.disposition is RecoveryCaseCreationDisposition.EXISTING
    assert result.recovery_case is existing_case
    assert result.audit_event is None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    append_audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ineligible_payment_is_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_attempt = create_payment_attempt(
        state=PaymentState.AUTHORIZED,
        recovery_eligible=False,
        recovery_stopped=True,
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(payment_attempt),
        query_result(None),
    ]
    append_audit = AsyncMock()
    monkeypatch.setattr(
        recovery_case_service,
        "append_recovery_audit_event",
        append_audit,
    )

    result = await create_or_get_recovery_case(
        session,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        opened_at=OPENED_AT,
        customer_contact_allowed=True,
    )

    assert result.disposition is RecoveryCaseCreationDisposition.INELIGIBLE
    assert result.recovery_case is None
    assert result.ineligibility_reasons == (
        RecoveryCaseIneligibilityReason.PAYMENT_NOT_FAILED,
        RecoveryCaseIneligibilityReason.RECOVERY_NOT_ELIGIBLE,
        RecoveryCaseIneligibilityReason.RECOVERY_ALREADY_STOPPED,
    )
    session.add.assert_not_called()
    append_audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_payment_attempt_is_rejected() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result(None)

    with pytest.raises(PaymentAttemptNotFoundError, match=str(PAYMENT_ATTEMPT_ID)):
        await create_or_get_recovery_case(
            session,
            payment_attempt_id=PAYMENT_ATTEMPT_ID,
            opened_at=OPENED_AT,
            customer_contact_allowed=False,
        )

    assert session.execute.await_count == 1
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_rejects_naive_opening_time_before_database_access() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="timezone-aware"):
        await create_or_get_recovery_case(
            session,
            payment_attempt_id=PAYMENT_ATTEMPT_ID,
            opened_at=datetime(2026, 8, 25, 8, 0),
            customer_contact_allowed=False,
        )

    session.execute.assert_not_awaited()
