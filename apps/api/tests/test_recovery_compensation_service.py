from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryCase,
)
from app.domain.payments import PaymentState
from app.domain.recovery import (
    RecoveryActionType,
    RecoveryCaseStatus,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkStatus,
)
from app.services import recovery_compensation_service
from app.services.recovery_action_executor import (
    build_payment_link_reference_id,
)
from app.services.recovery_compensation_service import (
    PreparedRecoveryCompensation,
    RecoveryCompensationDisposition,
    RecoveryCompensationNotRequiredError,
    complete_late_authorization_compensation,
    prepare_late_authorization_compensation,
    record_late_authorization_compensation_failure,
)

NOW = datetime(2026, 8, 25, 16, 30, tzinfo=UTC)

CASE_ID = UUID(
    "92000000-0000-0000-0000-000000000001",
)
PAYMENT_ID = UUID(
    "92000000-0000-0000-0000-000000000002",
)
LINK_ACTION_ID = UUID(
    "92000000-0000-0000-0000-000000000003",
)
MESSAGE_ACTION_ID = UUID(
    "92000000-0000-0000-0000-000000000004",
)
AGENT_RUN_ID = UUID(
    "92000000-0000-0000-0000-000000000005",
)

PAYMENT_LINK_ID = "plink_compensation_test"


def query_result(
    value: object | None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def collection_result(
    values: list[RecoveryAction],
) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def create_case(
    *,
    status: RecoveryCaseStatus = (RecoveryCaseStatus.READY),
    active_payment_link_id: str | None = (PAYMENT_LINK_ID),
    late_authorization_detected_at: (datetime | None) = None,
) -> RecoveryCase:
    return RecoveryCase(
        id=CASE_ID,
        payment_attempt_id=PAYMENT_ID,
        status=status.value,
        amount_minor=100,
        currency="INR",
        payment_method="upi",
        recovery_attempt_count=1,
        version=3,
        customer_contact_allowed=True,
        active_payment_link_id=(active_payment_link_id),
        late_authorization_detected_at=(late_authorization_detected_at),
        opened_at=NOW - timedelta(minutes=10),
    )


def create_payment(
    *,
    state: PaymentState = PaymentState.AUTHORIZED,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=PAYMENT_ID,
        provider="razorpay",
        provider_payment_id=("pay_compensation_test"),
        amount_minor=100,
        currency="INR",
        method="upi",
        payment_created_at=(NOW - timedelta(minutes=11)),
        current_state=state.value,
        state_version=2,
        state_provider_event_id=("evt_compensation_test"),
        state_webhook_event_id=UUID(
            "92000000-0000-0000-0000-000000000006",
        ),
        state_event_created_at=(NOW - timedelta(minutes=1)),
        recovery_eligible=False,
        recovery_stopped_at=(NOW - timedelta(minutes=1)),
        recovery_stop_reason=("late_authorization"),
        late_authorization_detected_at=(
            NOW - timedelta(minutes=1) if state is not PaymentState.FAILED else None
        ),
    )


def create_action(
    *,
    action_id: UUID = LINK_ACTION_ID,
    action_type: RecoveryActionType = (RecoveryActionType.CREATE_PAYMENT_LINK),
    status: RecoveryActionStatus = (RecoveryActionStatus.SUCCEEDED),
) -> RecoveryAction:
    return RecoveryAction(
        id=action_id,
        recovery_case_id=CASE_ID,
        agent_run_id=AGENT_RUN_ID,
        sequence_number=(1 if action_id == LINK_ACTION_ID else 2),
        idempotency_key=action_id.hex,
        action_type=action_type.value,
        status=status.value,
        proposal_reason="Recovery action",
        amount_minor=(100 if action_type is RecoveryActionType.CREATE_PAYMENT_LINK else None),
        currency=("INR" if action_type is RecoveryActionType.CREATE_PAYMENT_LINK else None),
        channel=("email" if action_type is RecoveryActionType.SEND_RECOVERY_MESSAGE else None),
        policy_outcome="allow",
        policy_guardrails=[],
        policy_explanation="Allowed",
        policy_version="deterministic-v1",
        policy_evaluated_at=(NOW - timedelta(minutes=5)),
        execution_attempt_count=(1 if status is RecoveryActionStatus.SUCCEEDED else 0),
        provider_action_id=(
            PAYMENT_LINK_ID if action_type is RecoveryActionType.CREATE_PAYMENT_LINK else None
        ),
        provider_action_status=(
            "created" if action_type is RecoveryActionType.CREATE_PAYMENT_LINK else None
        ),
        completed_at=(
            NOW - timedelta(minutes=2) if status is RecoveryActionStatus.SUCCEEDED else None
        ),
    )


def create_prepared() -> PreparedRecoveryCompensation:
    return PreparedRecoveryCompensation(
        recovery_case_id=CASE_ID,
        payment_attempt_id=PAYMENT_ID,
        payment_link_action_id=LINK_ACTION_ID,
        payment_link_id=PAYMENT_LINK_ID,
        reference_id=(
            build_payment_link_reference_id(
                LINK_ACTION_ID,
            )
        ),
    )


def create_provider_link(
    status: RazorpayPaymentLinkStatus,
) -> RazorpayPaymentLink:
    return RazorpayPaymentLink.model_validate(
        {
            "id": PAYMENT_LINK_ID,
            "short_url": ("https://rzp.io/i/compensation"),
            "status": status.value,
            "amount": 100,
            "currency": "INR",
            "reference_id": (
                build_payment_link_reference_id(
                    LINK_ACTION_ID,
                )
            ),
        },
    )


def patch_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncMock:
    append_audit = AsyncMock()

    monkeypatch.setattr(
        recovery_compensation_service,
        "append_recovery_audit_event",
        append_audit,
    )

    return append_audit


@pytest.mark.asyncio
async def test_prepares_compensation_and_cancels_pending_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case()
    payment = create_payment()
    link_action = create_action()

    message_action = create_action(
        action_id=MESSAGE_ACTION_ID,
        action_type=(RecoveryActionType.SEND_RECOVERY_MESSAGE),
        status=RecoveryActionStatus.ALLOWED,
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(payment),
        query_result(link_action),
        collection_result(
            [
                link_action,
                message_action,
            ],
        ),
    ]

    append_audit = patch_audit(monkeypatch)

    result = await prepare_late_authorization_compensation(
        session,
        recovery_case_id=CASE_ID,
        detected_at=NOW,
    )

    assert result.prepared == create_prepared()
    assert result.terminal_result is None

    assert message_action.status == RecoveryActionStatus.CANCELLED.value
    assert message_action.completed_at == NOW

    assert recovery_case.status == RecoveryCaseStatus.EXECUTING.value
    assert recovery_case.late_authorization_detected_at == NOW - timedelta(minutes=1)
    assert recovery_case.version == 4

    append_audit.assert_awaited_once()

    request = append_audit.await_args.kwargs["request"]

    assert request.event_type == "recovery.late_authorization.detected"
    assert request.event_data["cancelled_action_ids"] == [str(MESSAGE_ACTION_ID)]


@pytest.mark.asyncio
async def test_failed_payment_does_not_require_compensation() -> None:
    recovery_case = create_case()

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(
            create_payment(
                state=PaymentState.FAILED,
            ),
        ),
    ]

    with pytest.raises(
        RecoveryCompensationNotRequiredError,
        match="does not require",
    ):
        await prepare_late_authorization_compensation(
            session,
            recovery_case_id=CASE_ID,
            detected_at=NOW,
        )


@pytest.mark.asyncio
async def test_already_cancelled_case_is_idempotent() -> None:
    recovery_case = create_case(
        status=RecoveryCaseStatus.CANCELLED,
        active_payment_link_id=None,
        late_authorization_detected_at=(NOW - timedelta(minutes=1)),
    )
    recovery_case.closed_at = NOW - timedelta(minutes=1)

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result(
        recovery_case,
    )

    result = await prepare_late_authorization_compensation(
        session,
        recovery_case_id=CASE_ID,
        detected_at=NOW,
    )

    assert result.prepared is None
    assert result.terminal_result is not None
    assert result.terminal_result.disposition is RecoveryCompensationDisposition.ALREADY_CANCELLED

    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_completes_cancelled_payment_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case(
        status=RecoveryCaseStatus.EXECUTING,
        late_authorization_detected_at=(NOW - timedelta(minutes=1)),
    )
    link_action = create_action()

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(link_action),
    ]

    append_audit = patch_audit(monkeypatch)

    result = await complete_late_authorization_compensation(
        session,
        prepared=create_prepared(),
        payment_link=create_provider_link(
            RazorpayPaymentLinkStatus.CANCELLED,
        ),
        completed_at=NOW,
    )

    assert result.disposition is RecoveryCompensationDisposition.CANCELLED
    assert recovery_case.status == RecoveryCaseStatus.CANCELLED.value
    assert recovery_case.active_payment_link_id is None
    assert recovery_case.closed_at == NOW
    assert recovery_case.close_reason == ("late_authorization_payment_link_cancelled")
    assert link_action.provider_action_status == "cancelled"

    request = append_audit.await_args.kwargs["request"]

    assert request.event_type == "action.payment_link.cancelled"


@pytest.mark.asyncio
async def test_paid_recovery_link_requires_human_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case(
        status=RecoveryCaseStatus.EXECUTING,
        late_authorization_detected_at=(NOW - timedelta(minutes=1)),
    )
    link_action = create_action()

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(link_action),
    ]

    append_audit = patch_audit(monkeypatch)

    result = await complete_late_authorization_compensation(
        session,
        prepared=create_prepared(),
        payment_link=create_provider_link(
            RazorpayPaymentLinkStatus.PAID,
        ),
        completed_at=NOW,
    )

    assert result.disposition is RecoveryCompensationDisposition.ESCALATED
    assert recovery_case.status == RecoveryCaseStatus.ESCALATED.value
    assert recovery_case.active_payment_link_id == PAYMENT_LINK_ID
    assert recovery_case.closed_at is None
    assert link_action.provider_action_status == "paid"

    request = append_audit.await_args.kwargs["request"]

    assert request.event_type == ("action.payment_link.cancellation_escalated")


@pytest.mark.asyncio
async def test_provider_failure_is_safely_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_case = create_case(
        status=RecoveryCaseStatus.EXECUTING,
        late_authorization_detected_at=(NOW - timedelta(minutes=1)),
    )
    link_action = create_action()

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(recovery_case),
        query_result(link_action),
    ]

    append_audit = patch_audit(monkeypatch)

    error = RazorpayPaymentLinkProviderError(
        "provider body must not be persisted",
        retryable=True,
        status_code=503,
    )

    await record_late_authorization_compensation_failure(
        session,
        prepared=create_prepared(),
        error=error,
        failed_at=NOW,
    )

    assert link_action.last_error == (
        "RazorpayPaymentLinkProviderError(retryable=True, status_code=503)"
    )
    assert "provider body" not in link_action.last_error
    assert recovery_case.next_action_at == NOW + timedelta(minutes=1)

    request = append_audit.await_args.kwargs["request"]

    assert request.event_type == ("action.payment_link.cancellation_failed")


@pytest.mark.asyncio
async def test_rejects_naive_compensation_time() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        await prepare_late_authorization_compensation(
            session,
            recovery_case_id=CASE_ID,
            detected_at=datetime(
                2026,
                8,
                25,
                16,
                30,
            ),
        )

    session.execute.assert_not_awaited()
