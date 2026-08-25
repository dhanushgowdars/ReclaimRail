from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.integrations.razorpay.payment_customers import (
    RazorpayPaymentCustomer,
    RazorpayPaymentCustomerProvider,
    RazorpayPaymentCustomerProviderError,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkRequest,
)
from app.services.recovery_action_executor import (
    PreparedPaymentLinkAction,
    attach_transient_customer_to_payment_link_request,
)

ACTION_ID = UUID("93000000-0000-0000-0000-000000000001")
CASE_ID = UUID("93000000-0000-0000-0000-000000000002")


def create_prepared(
    *,
    customer_contact_allowed: bool,
) -> PreparedPaymentLinkAction:
    return PreparedPaymentLinkAction(
        action_id=ACTION_ID,
        recovery_case_id=CASE_ID,
        provider_payment_id="pay_transient_customer_test",
        customer_contact_allowed=customer_contact_allowed,
        attempt_number=1,
        reference_id="rr_transient_customer_test",
        request=RazorpayPaymentLinkRequest(
            amount_minor=125_000,
            currency="INR",
            reference_id="rr_transient_customer_test",
            description="ReclaimRail recovery payment",
        ),
    )


@pytest.mark.asyncio
async def test_attaches_transient_contact_without_enabling_notification() -> None:
    provider = MagicMock(
        spec=RazorpayPaymentCustomerProvider,
    )
    provider.fetch_payment_customer = AsyncMock(
        return_value=RazorpayPaymentCustomer.model_validate(
            {
                "id": "pay_transient_customer_test",
                "email": "customer@example.test",
                "contact": "+919876543210",
            },
        ),
    )

    prepared = await attach_transient_customer_to_payment_link_request(
        create_prepared(
            customer_contact_allowed=True,
        ),
        customer_provider=provider,
    )

    provider.fetch_payment_customer.assert_awaited_once_with(
        "pay_transient_customer_test",
    )

    payload = prepared.request.to_provider_payload()

    assert payload["customer"] == {
        "email": "customer@example.test",
        "contact": "+919876543210",
    }
    assert "notify" not in payload
    assert "customer@example.test" not in repr(prepared.request)
    assert prepared.request.model_dump().get("customer_email") is None
    assert prepared.request.model_dump().get("customer_contact") is None


@pytest.mark.asyncio
async def test_skips_customer_lookup_without_contact_permission() -> None:
    provider = MagicMock(
        spec=RazorpayPaymentCustomerProvider,
    )
    provider.fetch_payment_customer = AsyncMock()

    prepared = await attach_transient_customer_to_payment_link_request(
        create_prepared(
            customer_contact_allowed=False,
        ),
        customer_provider=provider,
    )

    provider.fetch_payment_customer.assert_not_awaited()

    assert "customer" not in prepared.request.to_provider_payload()


@pytest.mark.asyncio
async def test_skips_customer_lookup_when_no_provider_is_configured() -> None:
    prepared = await attach_transient_customer_to_payment_link_request(
        create_prepared(
            customer_contact_allowed=True,
        ),
        customer_provider=None,
    )

    assert "customer" not in prepared.request.to_provider_payload()


@pytest.mark.asyncio
async def test_converts_customer_lookup_failure_to_safe_payment_link_error() -> None:
    provider = MagicMock(
        spec=RazorpayPaymentCustomerProvider,
    )
    provider.fetch_payment_customer = AsyncMock(
        side_effect=RazorpayPaymentCustomerProviderError(
            "customer lookup provider error",
            retryable=True,
            status_code=503,
        ),
    )

    with pytest.raises(
        RazorpayPaymentLinkProviderError,
    ) as caught:
        await attach_transient_customer_to_payment_link_request(
            create_prepared(
                customer_contact_allowed=True,
            ),
            customer_provider=provider,
        )

    assert caught.value.retryable is True
    assert caught.value.status_code == 503
    assert "customer lookup provider error" not in str(caught.value)
