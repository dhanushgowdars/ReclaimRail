from app.integrations.razorpay.payment_events import (
    PaymentEventNormalizationError,
    normalize_razorpay_payment_link_event,
)
from app.integrations.razorpay.webhooks import RazorpayWebhookEnvelope


def _envelope(*, event: str, status: str) -> RazorpayWebhookEnvelope:
    return RazorpayWebhookEnvelope.model_validate(
        {
            "entity": "event",
            "event": event,
            "contains": ["payment_link"],
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_event_test",
                        "short_url": "https://rzp.io/i/event-test",
                        "status": status,
                        "amount": 349_900,
                        "amount_paid": 349_900 if status == "paid" else 0,
                        "currency": "inr",
                        "reference_id": "rr_event_test",
                        "updated_at": 1_787_550_000,
                    },
                },
            },
            "created_at": 1_787_550_000,
        },
    )


def test_normalizes_paid_payment_link_webhook() -> None:
    result = normalize_razorpay_payment_link_event(
        provider_event_id="evt_payment_link_paid",
        envelope=_envelope(event="payment_link.paid", status="paid"),
    )

    assert result.payment_link.payment_link_id == "plink_event_test"
    assert result.payment_link.amount_paid_minor == 349_900
    assert result.payment_link.currency == "INR"


def test_rejects_payment_link_event_status_mismatch() -> None:
    try:
        normalize_razorpay_payment_link_event(
            provider_event_id="evt_payment_link_bad",
            envelope=_envelope(event="payment_link.paid", status="created"),
        )
    except PaymentEventNormalizationError as error:
        assert "do not match" in str(error)
    else:
        raise AssertionError("Expected a status mismatch to be rejected")
