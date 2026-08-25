import pytest
from pydantic import ValidationError

from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkRequest,
)


def build_request(
    **changes: object,
) -> RazorpayPaymentLinkRequest:
    values: dict[str, object] = {
        "amount_minor": 125_000,
        "currency": "INR",
        "reference_id": "rr_contact_payload_test",
        "description": "ReclaimRail recovery payment",
    }
    values.update(changes)

    return RazorpayPaymentLinkRequest(
        **values,
    )


def test_builds_transient_customer_payload_without_automatic_notification() -> None:
    request = build_request(
        customer_email="customer@example.test",
        customer_contact="+919876543210",
    )

    payload = request.to_provider_payload()

    assert payload["customer"] == {
        "email": "customer@example.test",
        "contact": "+919876543210",
    }
    assert "notify" not in payload
    assert "customer@example.test" not in repr(request)
    assert request.model_dump().get("customer_email") is None
    assert request.model_dump().get("customer_contact") is None


def test_builds_notification_payload_only_for_the_requested_channel() -> None:
    request = build_request(
        customer_email="customer@example.test",
        notify_email=True,
    )

    payload = request.to_provider_payload()

    assert payload["customer"] == {
        "email": "customer@example.test",
    }
    assert payload["notify"] == {
        "email": True,
        "sms": False,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"notify_email": True},
        {"notify_sms": True},
        {
            "customer_email": " ",
            "notify_email": True,
        },
        {
            "customer_contact": " ",
            "notify_sms": True,
        },
    ],
)
def test_rejects_notification_without_required_transient_contact(
    changes: dict[str, object],
) -> None:
    with pytest.raises(
        ValidationError,
    ):
        build_request(
            **changes,
        )
