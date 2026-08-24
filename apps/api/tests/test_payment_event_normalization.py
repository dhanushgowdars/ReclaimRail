from uuid import UUID

import pytest

from app.domain.payments import PaymentState
from app.integrations.razorpay.payment_events import (
    PaymentEventNormalizationError,
    UnsupportedPaymentEventError,
    normalize_razorpay_payment_event,
    timestamp_to_datetime,
)
from app.integrations.razorpay.webhooks import (
    RazorpayWebhookEnvelope,
)

WEBHOOK_EVENT_ID = UUID(
    "12345678-1234-5678-1234-567812345678",
)
PROVIDER_EVENT_ID = "evt_payment_normalization_001"
EVENT_CREATED_AT = 1_787_550_000
PAYMENT_CREATED_AT = 1_787_549_000


def make_envelope(
    *,
    event_type: str = "payment.failed",
    payment_status: str = "failed",
    overrides: dict[str, object] | None = None,
) -> RazorpayWebhookEnvelope:
    payment: dict[str, object] = {
        "id": "pay_reclaimrail_001",
        "entity": "payment",
        "amount": 49_900,
        "currency": "inr",
        "status": payment_status,
        "order_id": "order_reclaimrail_001",
        "method": "upi",
        "created_at": PAYMENT_CREATED_AT,
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment failed",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "payment_failed",
    }

    if overrides is not None:
        payment.update(overrides)

    return RazorpayWebhookEnvelope(
        entity="event",
        account_id="acc_reclaimrail_test",
        event=event_type,
        contains=["payment"],
        payload={
            "payment": {
                "entity": payment,
            },
        },
        created_at=EVENT_CREATED_AT,
    )


def test_normalizes_failed_payment_without_customer_pii() -> None:
    normalized = normalize_razorpay_payment_event(
        webhook_event_id=WEBHOOK_EVENT_ID,
        provider_event_id=PROVIDER_EVENT_ID,
        envelope=make_envelope(),
    )

    assert normalized.webhook_event_id == WEBHOOK_EVENT_ID
    assert normalized.provider_event_id == PROVIDER_EVENT_ID
    assert normalized.provider == "razorpay"
    assert normalized.account_id == "acc_reclaimrail_test"
    assert normalized.event_type == "payment.failed"

    assert normalized.payment_id == "pay_reclaimrail_001"
    assert normalized.order_id == "order_reclaimrail_001"
    assert normalized.state is PaymentState.FAILED

    assert normalized.amount_minor == 49_900
    assert normalized.currency == "INR"
    assert normalized.method == "upi"

    assert normalized.event_created_at == timestamp_to_datetime(
        EVENT_CREATED_AT,
    )
    assert normalized.payment_created_at == timestamp_to_datetime(
        PAYMENT_CREATED_AT,
    )

    assert normalized.error_code == "BAD_REQUEST_ERROR"
    assert normalized.error_description == "Payment failed"
    assert normalized.error_source == "customer"
    assert normalized.error_step == "payment_authentication"
    assert normalized.error_reason == "payment_failed"

    assert not hasattr(normalized, "email")
    assert not hasattr(normalized, "contact")


@pytest.mark.parametrize(
    ("event_type", "payment_status", "expected_state"),
    [
        (
            "payment.authorized",
            "authorized",
            PaymentState.AUTHORIZED,
        ),
        (
            "payment.captured",
            "captured",
            PaymentState.CAPTURED,
        ),
        (
            "payment.refunded",
            "refunded",
            PaymentState.REFUNDED,
        ),
    ],
)
def test_normalizes_supported_success_events(
    event_type: str,
    payment_status: str,
    expected_state: PaymentState,
) -> None:
    normalized = normalize_razorpay_payment_event(
        webhook_event_id=WEBHOOK_EVENT_ID,
        provider_event_id=PROVIDER_EVENT_ID,
        envelope=make_envelope(
            event_type=event_type,
            payment_status=payment_status,
        ),
    )

    assert normalized.state is expected_state
    assert normalized.event_type == event_type


def test_rejects_unsupported_event_type() -> None:
    with pytest.raises(
        UnsupportedPaymentEventError,
        match="Unsupported Razorpay payment event",
    ):
        normalize_razorpay_payment_event(
            webhook_event_id=WEBHOOK_EVENT_ID,
            provider_event_id=PROVIDER_EVENT_ID,
            envelope=make_envelope(
                event_type="order.paid",
                payment_status="captured",
            ),
        )


def test_rejects_missing_payment_object() -> None:
    envelope = RazorpayWebhookEnvelope(
        entity="event",
        account_id="acc_reclaimrail_test",
        event="payment.failed",
        contains=["payment"],
        payload={},
        created_at=EVENT_CREATED_AT,
    )

    with pytest.raises(
        PaymentEventNormalizationError,
        match="does not contain a payment object",
    ):
        normalize_razorpay_payment_event(
            webhook_event_id=WEBHOOK_EVENT_ID,
            provider_event_id=PROVIDER_EVENT_ID,
            envelope=envelope,
        )


def test_rejects_event_and_status_mismatch() -> None:
    with pytest.raises(
        PaymentEventNormalizationError,
        match="do not match",
    ):
        normalize_razorpay_payment_event(
            webhook_event_id=WEBHOOK_EVENT_ID,
            provider_event_id=PROVIDER_EVENT_ID,
            envelope=make_envelope(
                event_type="payment.failed",
                payment_status="authorized",
            ),
        )


def test_rejects_invalid_payment_entity() -> None:
    with pytest.raises(
        PaymentEventNormalizationError,
        match="invalid payment entity",
    ):
        normalize_razorpay_payment_event(
            webhook_event_id=WEBHOOK_EVENT_ID,
            provider_event_id=PROVIDER_EVENT_ID,
            envelope=make_envelope(
                overrides={
                    "amount": -1,
                },
            ),
        )


def test_uses_event_timestamp_when_payment_timestamp_is_missing() -> None:
    normalized = normalize_razorpay_payment_event(
        webhook_event_id=WEBHOOK_EVENT_ID,
        provider_event_id=PROVIDER_EVENT_ID,
        envelope=make_envelope(
            overrides={
                "created_at": None,
            },
        ),
    )

    assert normalized.payment_created_at == normalized.event_created_at
