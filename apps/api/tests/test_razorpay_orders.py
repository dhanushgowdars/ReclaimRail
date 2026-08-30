import base64
import json

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.integrations.razorpay.orders import (
    RazorpayOrderProvider,
    RazorpayOrderProviderError,
    RazorpayOrderRequest,
    RazorpayOrderStatus,
    create_razorpay_order_provider,
)


def build_request() -> RazorpayOrderRequest:
    return RazorpayOrderRequest(
        amount_minor=349_900,
        currency=" inr ",
        receipt=" rr_lab_001 ",
        notes={" run_id ": " run-001 "},
    )


def success_payload() -> dict[str, object]:
    return {
        "id": "order_test_001",
        "amount": 349_900,
        "amount_paid": 0,
        "amount_due": 349_900,
        "currency": "INR",
        "receipt": "rr_lab_001",
        "status": "created",
        "attempts": 0,
        "created_at": 1_777_392_000,
    }


def test_normalizes_bounded_order_request() -> None:
    request = build_request()

    assert request.currency == "INR"
    assert request.receipt == "rr_lab_001"
    assert request.notes == {"run_id": "run-001"}
    assert request.to_provider_payload() == {
        "amount": 349_900,
        "currency": "INR",
        "receipt": "rr_lab_001",
        "partial_payment": False,
        "notes": {"run_id": "run-001"},
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": 9},
        {"currency": "IN"},
        {"receipt": " "},
        {"receipt": "x" * 41},
        {"notes": {"": "value"}},
    ],
)
def test_rejects_invalid_order_request(changes: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "amount_minor": 349_900,
        "currency": "INR",
        "receipt": "rr_lab_001",
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        RazorpayOrderRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_creates_order_with_basic_auth_and_safe_payload() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://api.razorpay.test/v1/orders"

        credentials = request.headers["Authorization"].removeprefix("Basic ")
        assert base64.b64decode(credentials).decode() == "rzp_test_key:test-secret"
        assert json.loads(request.content) == build_request().to_provider_payload()

        return httpx2.Response(200, request=request, json=success_payload())

    provider = RazorpayOrderProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(handler),
    )

    order = await provider.create_order(build_request())

    assert order.order_id == "order_test_001"
    assert order.status is RazorpayOrderStatus.CREATED
    assert order.amount_minor == 349_900
    assert provider.checkout_key_id == "rzp_test_key"
    assert "test-secret" not in repr(provider)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(400, False), (401, False), (429, True), (503, True)],
)
async def test_classifies_provider_failures(
    status_code: int,
    retryable: bool,
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status_code,
            request=request,
            json={"error": "sensitive-provider-detail"},
        )

    provider = RazorpayOrderProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(handler),
    )

    with pytest.raises(RazorpayOrderProviderError) as caught:
        await provider.create_order(build_request())

    assert caught.value.retryable is retryable
    assert caught.value.status_code == status_code
    assert "sensitive-provider-detail" not in str(caught.value)


def test_factory_allows_test_keys_only() -> None:
    test_provider = create_razorpay_order_provider(
        Settings(
            razorpay_key_id=SecretStr("rzp_test_key"),
            razorpay_key_secret=SecretStr("test-secret"),
        ),
    )
    live_provider = create_razorpay_order_provider(
        Settings(
            razorpay_key_id=SecretStr("rzp_live_key"),
            razorpay_key_secret=SecretStr("live-secret"),
        ),
    )

    assert test_provider is not None
    assert live_provider is None
