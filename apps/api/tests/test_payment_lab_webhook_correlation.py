from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment_lab import (
    PaymentLabRun,
    PaymentLabRunMode,
    PaymentLabRunProvenance,
    PaymentLabRunStatus,
)
from app.domain.payments import (
    PaymentLifecycleEvent,
    PaymentState,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
)
from app.services.payment_lab_webhook_correlation import (
    PaymentLabWebhookCorrelationDisposition,
    PaymentLabWebhookCorrelationError,
    PreparedPaymentLabWebhookCorrelation,
    apply_payment_lab_webhook_correlation,
    prepare_payment_lab_webhook_correlation,
)
from app.services.payment_projector import PaymentProjectionResult

RUN_ID = UUID("10000000-0000-0000-0000-000000000001")
WEBHOOK_ID = UUID("20000000-0000-0000-0000-000000000001")
ATTEMPT_ID = UUID("30000000-0000-0000-0000-000000000001")
CLIENT_REQUEST_ID = UUID("40000000-0000-0000-0000-000000000001")
OBSERVED_AT = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def build_run() -> PaymentLabRun:
    return PaymentLabRun(
        id=RUN_ID,
        client_request_id=CLIENT_REQUEST_ID,
        mode=PaymentLabRunMode.GUIDED.value,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        status=PaymentLabRunStatus.CHECKOUT_READY.value,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        receipt="rrlab_test_receipt",
        provider_order_id="order_payment_lab_test",
        provider_order_status="created",
        provider_created_at=OBSERVED_AT - timedelta(minutes=1),
        payment_attempt_id=None,
        failure_code=None,
        checkout_expires_at=OBSERVED_AT + timedelta(minutes=9),
        created_at=OBSERVED_AT - timedelta(minutes=1),
        updated_at=OBSERVED_AT - timedelta(minutes=1),
        version=1,
    )


def build_event(
    *,
    amount_minor: int = 349_900,
    method: str = "netbanking",
) -> PaymentLifecycleEvent:
    return PaymentLifecycleEvent(
        webhook_event_id=WEBHOOK_ID,
        provider_event_id="evt_payment_lab_failed",
        provider="razorpay",
        account_id="acc_payment_lab_test",
        event_type="payment.failed",
        payment_id="pay_payment_lab_test",
        order_id="order_payment_lab_test",
        state=PaymentState.FAILED,
        amount_minor=amount_minor,
        currency="INR",
        method=method,
        event_created_at=OBSERVED_AT,
        payment_created_at=OBSERVED_AT - timedelta(seconds=10),
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment declined",
        error_source="bank",
        error_step="payment_authorization",
        error_reason="payment_failed",
    )


def build_projection(
    *,
    state: PaymentState = PaymentState.FAILED,
) -> PaymentProjectionResult:
    return PaymentProjectionResult(
        payment_attempt_id=ATTEMPT_ID,
        webhook_event_id=WEBHOOK_ID,
        state=state,
        state_version=1,
        outcome=PaymentTransitionOutcome.APPLIED,
        reason=PaymentTransitionReason.INITIALIZED,
        duplicate=False,
    )


def optional_scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_signed_failure_links_payment_lab_run_to_projection() -> None:
    payment_lab_run = build_run()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        payment_lab_run,
    )
    event = build_event()

    prepared = await prepare_payment_lab_webhook_correlation(
        session,
        event,
    )

    assert prepared is not None

    result = apply_payment_lab_webhook_correlation(
        prepared,
        event,
        build_projection(),
        observed_at=OBSERVED_AT,
    )

    assert result.disposition is (PaymentLabWebhookCorrelationDisposition.CORRELATED)
    assert result.status is PaymentLabRunStatus.PAYMENT_ATTEMPTED
    assert payment_lab_run.payment_attempt_id == ATTEMPT_ID
    assert payment_lab_run.status == PaymentLabRunStatus.PAYMENT_ATTEMPTED.value
    assert payment_lab_run.failure_code == "BAD_REQUEST_ERROR"
    assert payment_lab_run.updated_at == OBSERVED_AT
    assert payment_lab_run.version == 2


@pytest.mark.asyncio
async def test_provider_verified_method_replaces_checkout_hint() -> None:
    payment_lab_run = build_run()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(payment_lab_run)
    event = build_event(method="card")

    prepared = await prepare_payment_lab_webhook_correlation(session, event)

    assert prepared is not None
    result = apply_payment_lab_webhook_correlation(
        prepared,
        event,
        build_projection(),
        observed_at=OBSERVED_AT,
    )

    assert result.status is PaymentLabRunStatus.PAYMENT_ATTEMPTED
    assert payment_lab_run.payment_method == "card"
    assert payment_lab_run.payment_attempt_id == ATTEMPT_ID


@pytest.mark.asyncio
async def test_unmodelled_provider_method_does_not_break_run_correlation() -> None:
    payment_lab_run = build_run()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(payment_lab_run)
    event = build_event(method="paylater")

    prepared = await prepare_payment_lab_webhook_correlation(session, event)

    assert prepared is not None
    result = apply_payment_lab_webhook_correlation(
        prepared,
        event,
        build_projection(),
        observed_at=OBSERVED_AT,
    )

    assert result.status is PaymentLabRunStatus.PAYMENT_ATTEMPTED
    assert payment_lab_run.payment_method == "netbanking"


@pytest.mark.asyncio
async def test_unmatched_provider_order_is_not_a_payment_lab_run() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(None)

    result = await prepare_payment_lab_webhook_correlation(
        session,
        build_event(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_conflicting_amount_is_rejected_before_projection() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        build_run(),
    )

    with pytest.raises(
        PaymentLabWebhookCorrelationError,
        match="amount",
    ):
        await prepare_payment_lab_webhook_correlation(
            session,
            build_event(amount_minor=349_800),
        )


@pytest.mark.asyncio
async def test_replay_does_not_increment_run_version() -> None:
    payment_lab_run = build_run()
    payment_lab_run.payment_attempt_id = ATTEMPT_ID
    payment_lab_run.status = PaymentLabRunStatus.PAYMENT_ATTEMPTED.value
    payment_lab_run.failure_code = "BAD_REQUEST_ERROR"
    session = AsyncMock(spec=AsyncSession)

    linked_attempt = MagicMock()
    linked_attempt.provider = "razorpay"
    linked_attempt.provider_payment_id = "pay_payment_lab_test"
    linked_attempt.provider_order_id = "order_payment_lab_test"
    session.execute.side_effect = [
        optional_scalar_result(payment_lab_run),
        optional_scalar_result(linked_attempt),
    ]

    event = build_event()
    prepared = await prepare_payment_lab_webhook_correlation(
        session,
        event,
    )

    assert prepared is not None

    result = apply_payment_lab_webhook_correlation(
        prepared,
        event,
        build_projection(),
        observed_at=OBSERVED_AT,
    )

    assert result.disposition is (PaymentLabWebhookCorrelationDisposition.ALREADY_CURRENT)
    assert payment_lab_run.version == 1


def test_out_of_order_failure_cannot_regress_completed_run() -> None:
    payment_lab_run = build_run()
    payment_lab_run.payment_attempt_id = ATTEMPT_ID
    payment_lab_run.status = PaymentLabRunStatus.COMPLETED.value
    payment_lab_run.failure_code = None
    prepared = PreparedPaymentLabWebhookCorrelation(
        payment_lab_run=payment_lab_run,
    )

    result = apply_payment_lab_webhook_correlation(
        prepared,
        build_event(),
        build_projection(state=PaymentState.CAPTURED),
        observed_at=OBSERVED_AT,
    )

    assert result.disposition is (PaymentLabWebhookCorrelationDisposition.ALREADY_CURRENT)
    assert result.status is PaymentLabRunStatus.COMPLETED
    assert payment_lab_run.failure_code is None
    assert payment_lab_run.version == 1
