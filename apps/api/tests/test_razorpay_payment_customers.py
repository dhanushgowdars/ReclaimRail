import base64

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.razorpay.payment_customers import (
    RazorpayPaymentCustomerProvider,
    RazorpayPaymentCustomerProviderError,
    create_razorpay_payment_customer_provider,
)


def create_provider(
    transport: httpx2.AsyncBaseTransport,
) -> RazorpayPaymentCustomerProvider:
    return RazorpayPaymentCustomerProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=transport,
    )


@pytest.mark.asyncio
async def test_fetches_customer_without_exposing_contact_data() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        assert request.method == "GET"
        assert str(request.url) == ("https://api.razorpay.test/v1/payments/pay_test_001")

        encoded_credentials = request.headers["Authorization"].removeprefix("Basic ")

        assert base64.b64decode(encoded_credentials).decode() == ("rzp_test_key:test-secret")

        return httpx2.Response(
            200,
            request=request,
            json={
                "id": "pay_test_001",
                "email": " customer@example.com ",
                "contact": " +919876543210 ",
                "notes": {
                    "ignored": "provider-data",
                },
            },
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    customer = await provider.fetch_payment_customer(
        " pay_test_001 ",
    )

    assert customer.provider_payment_id == "pay_test_001"
    assert customer.email == "customer@example.com"
    assert customer.contact == "+919876543210"
    assert customer.has_email is True
    assert customer.has_contact is True

    representation = repr(customer)
    serialized = customer.model_dump_json()

    assert "customer@example.com" not in representation
    assert "+919876543210" not in representation
    assert "customer@example.com" not in serialized
    assert "+919876543210" not in serialized


@pytest.mark.asyncio
async def test_normalizes_blank_contact_values_to_none() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            json={
                "id": "pay_test_001",
                "email": " ",
                "contact": None,
            },
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    customer = await provider.fetch_payment_customer(
        "pay_test_001",
    )

    assert customer.email is None
    assert customer.contact is None
    assert customer.has_email is False
    assert customer.has_contact is False


@pytest.mark.parametrize(
    "provider_payment_id",
    [
        " ",
        "x" * 129,
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_payment_id(
    provider_payment_id: str,
) -> None:
    provider = RazorpayPaymentCustomerProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
    )

    with pytest.raises(ValueError):
        await provider.fetch_payment_customer(
            provider_payment_id,
        )


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (400, False),
        (401, False),
        (429, True),
        (503, True),
    ],
)
@pytest.mark.asyncio
async def test_classifies_provider_http_failure(
    status_code: int,
    retryable: bool,
) -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            status_code,
            request=request,
            json={
                "error": {
                    "description": ("customer@example.com +919876543210 sensitive provider error"),
                },
            },
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentCustomerProviderError,
    ) as caught:
        await provider.fetch_payment_customer(
            "pay_test_001",
        )

    assert caught.value.retryable is retryable
    assert caught.value.status_code == status_code
    assert "customer@example.com" not in str(caught.value)
    assert "+919876543210" not in str(caught.value)
    assert "sensitive provider error" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "id": "pay_test_001",
            "email": "x" * 321,
        },
        {
            "id": "pay_test_001",
            "contact": "9" * 33,
        },
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_customer_response(
    payload: dict[str, object],
) -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            json=payload,
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentCustomerProviderError,
    ) as caught:
        await provider.fetch_payment_customer(
            "pay_test_001",
        )

    assert caught.value.retryable is False
    assert caught.value.status_code == 200


@pytest.mark.asyncio
async def test_rejects_non_json_customer_response() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            content=b"not-json",
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentCustomerProviderError,
    ) as caught:
        await provider.fetch_payment_customer(
            "pay_test_001",
        )

    assert caught.value.retryable is False
    assert caught.value.status_code == 200


@pytest.mark.asyncio
async def test_rejects_mismatched_payment_response() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            json={
                "id": "pay_different",
                "email": "customer@example.com",
                "contact": "+919876543210",
            },
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentCustomerProviderError,
    ) as caught:
        await provider.fetch_payment_customer(
            "pay_test_001",
        )

    assert caught.value.retryable is False
    assert caught.value.status_code == 200
    assert "customer@example.com" not in str(caught.value)
    assert "+919876543210" not in str(caught.value)


@pytest.mark.asyncio
async def test_classifies_transport_failure_as_retryable() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        raise httpx2.ConnectError(
            "customer@example.com sensitive transport failure",
            request=request,
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentCustomerProviderError,
    ) as caught:
        await provider.fetch_payment_customer(
            "pay_test_001",
        )

    assert caught.value.retryable is True
    assert caught.value.status_code is None
    assert "customer@example.com" not in str(caught.value)
    assert "sensitive transport failure" not in str(caught.value)


def test_factory_requires_both_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "RECLAIMRAIL_RAZORPAY_KEY_ID",
        raising=False,
    )
    monkeypatch.delenv(
        "RECLAIMRAIL_RAZORPAY_KEY_SECRET",
        raising=False,
    )

    assert (
        create_razorpay_payment_customer_provider(
            Settings(
                _env_file=None,
                razorpay_key_id=None,
                razorpay_key_secret=None,
            ),
        )
        is None
    )

    assert (
        create_razorpay_payment_customer_provider(
            Settings(
                _env_file=None,
                razorpay_key_id=SecretStr("rzp_test_key"),
                razorpay_key_secret=None,
            ),
        )
        is None
    )


def test_factory_does_not_expose_key_secret() -> None:
    provider = create_razorpay_payment_customer_provider(
        Settings(
            _env_file=None,
            razorpay_key_id=SecretStr("rzp_test_key"),
            razorpay_key_secret=SecretStr("test-secret"),
        ),
    )

    assert provider is not None
    assert "test-secret" not in repr(provider)
