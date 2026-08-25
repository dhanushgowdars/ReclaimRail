import httpx2
import pytest
from pydantic import ValidationError

from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkStatus,
)


def build_provider_response(
    *,
    status: str = "paid",
    amount: int = 45_000,
    amount_paid: int = 45_000,
) -> dict[str, object]:
    return {
        "id": "plink_outcome_001",
        "short_url": "https://rzp.io/i/outcome001",
        "status": status,
        "amount": amount,
        "amount_paid": amount_paid,
        "currency": "INR",
        "reference_id": "rr_outcome_001",
        "updated_at": 1_778_000_000,
        "customer": {
            "email": "must-not-be-stored@example.com",
            "contact": "+919999999999",
        },
        "payments": [
            {
                "id": "pay_should_not_be_parsed",
            },
        ],
    }


@pytest.mark.asyncio
async def test_fetches_sanitised_payment_link_evidence_by_id() -> None:
    received_requests: list[httpx2.Request] = []

    def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        received_requests.append(request)

        return httpx2.Response(
            200,
            json=build_provider_response(),
            request=request,
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_key",
        key_secret="test_secret",
        transport=httpx2.MockTransport(handler),
    )

    payment_link = await provider.fetch_payment_link(
        "plink_outcome_001",
    )

    assert len(received_requests) == 1
    assert received_requests[0].method == "GET"
    assert received_requests[0].url.path == "/v1/payment_links/plink_outcome_001"

    assert payment_link.payment_link_id == "plink_outcome_001"
    assert payment_link.status is RazorpayPaymentLinkStatus.PAID
    assert payment_link.amount_minor == 45_000
    assert payment_link.amount_paid_minor == 45_000
    assert payment_link.currency == "INR"
    assert payment_link.reference_id == "rr_outcome_001"
    assert payment_link.provider_updated_at == 1_778_000_000

    serialised = payment_link.model_dump()
    assert "customer" not in serialised
    assert "payments" not in serialised


def test_defaults_missing_paid_amount_to_zero() -> None:
    payload = build_provider_response(
        status="created",
        amount_paid=0,
    )
    payload.pop("amount_paid")

    payment_link = RazorpayPaymentLink.model_validate(payload)

    assert payment_link.status is RazorpayPaymentLinkStatus.CREATED
    assert payment_link.amount_paid_minor == 0


def test_rejects_provider_paid_amount_above_link_amount() -> None:
    with pytest.raises(
        ValidationError,
        match="cannot exceed link amount",
    ):
        RazorpayPaymentLink.model_validate(
            build_provider_response(
                amount=45_000,
                amount_paid=45_001,
            ),
        )


@pytest.mark.asyncio
async def test_fetch_classifies_provider_server_failure_as_retryable() -> None:
    def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            503,
            json={"error": {"description": "temporary failure"}},
            request=request,
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_key",
        key_secret="test_secret",
        transport=httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentLinkProviderError,
    ) as error:
        await provider.fetch_payment_link(
            "plink_outcome_001",
        )

    assert error.value.retryable is True
    assert error.value.status_code == 503
