import base64
import json
from datetime import UTC, datetime

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkRequest,
    RazorpayPaymentLinkStatus,
    create_razorpay_payment_link_provider,
)


def create_request() -> RazorpayPaymentLinkRequest:
    return RazorpayPaymentLinkRequest(
        amount_minor=450_000,
        currency=" inr ",
        reference_id=" recovery-action-001 ",
        description=" Reclaim failed UPI payment ",
        expire_by=datetime(
            2026,
            8,
            26,
            12,
            0,
            tzinfo=UTC,
        ),
        notes={
            " recovery_case_id ": " case-001 ",
        },
    )


def success_payload() -> dict[str, object]:
    return {
        "id": "plink_test_001",
        "short_url": "https://rzp.io/i/test001",
        "status": "created",
        "amount": 450_000,
        "currency": "INR",
        "reference_id": "recovery-action-001",
    }


def test_normalizes_bounded_payment_link_request() -> None:
    request = create_request()

    assert request.currency == "INR"
    assert request.reference_id == "recovery-action-001"
    assert request.description == "Reclaim failed UPI payment"
    assert request.notes == {"recovery_case_id": "case-001"}

    assert request.to_provider_payload() == {
        "amount": 450_000,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": "recovery-action-001",
        "description": "Reclaim failed UPI payment",
        "reminder_enable": False,
        "expire_by": 1787745600,
        "notes": {"recovery_case_id": "case-001"},
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": 0},
        {"currency": "IN"},
        {"reference_id": " "},
        {
            "expire_by": datetime(
                2026,
                8,
                26,
                12,
                0,
            )
        },
        {"notes": {"": "value"}},
    ],
)
def test_rejects_invalid_payment_link_request(
    changes: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "amount_minor": 450_000,
        "currency": "INR",
        "reference_id": "recovery-action-001",
        "description": "Reclaim failed payment",
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        RazorpayPaymentLinkRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_creates_payment_link_with_basic_auth_and_safe_payload() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        assert str(request.url) == "https://api.razorpay.test/v1/payment_links"

        encoded_credentials = request.headers["Authorization"].removeprefix("Basic ")

        decoded_credentials = base64.b64decode(encoded_credentials).decode()

        assert decoded_credentials == "rzp_test_key:test-secret"

        assert json.loads(request.content) == create_request().to_provider_payload()

        return httpx2.Response(
            200,
            request=request,
            json=success_payload(),
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(handler),
    )

    result = await provider.create_payment_link(create_request())

    assert result.payment_link_id == "plink_test_001"
    assert result.status is RazorpayPaymentLinkStatus.CREATED
    assert result.amount_minor == 450_000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (400, False),
        (401, False),
        (429, True),
        (503, True),
    ],
)
async def test_classifies_provider_http_failures(
    status_code: int,
    retryable: bool,
) -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            status_code,
            request=request,
            json={"error": "safe-test"},
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(handler),
    )

    with pytest.raises(RazorpayPaymentLinkProviderError) as caught:
        await provider.create_payment_link(create_request())

    assert caught.value.status_code == status_code
    assert caught.value.retryable is retryable
    assert "safe-test" not in str(caught.value)


@pytest.mark.asyncio
async def test_rejects_invalid_success_response() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            json={"id": "missing-fields"},
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(handler),
    )

    with pytest.raises(RazorpayPaymentLinkProviderError) as caught:
        await provider.create_payment_link(create_request())

    assert caught.value.retryable is False
    assert caught.value.status_code == 200


@pytest.mark.asyncio
async def test_classifies_transport_failure_as_retryable() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        raise httpx2.ConnectError(
            "simulated connection failure",
            request=request,
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(handler),
    )

    with pytest.raises(RazorpayPaymentLinkProviderError) as caught:
        await provider.create_payment_link(create_request())

    assert caught.value.retryable is True
    assert caught.value.status_code is None
    assert "simulated connection failure" not in str(caught.value)


def test_factory_requires_both_credentials() -> None:
    assert (
        create_razorpay_payment_link_provider(
            Settings(
                razorpay_key_id=None,
                razorpay_key_secret=None,
            )
        )
        is None
    )

    assert (
        create_razorpay_payment_link_provider(
            Settings(
                razorpay_key_id=None,
                razorpay_key_secret=None,
            )
        )
        is None
    )


def test_factory_does_not_expose_key_secret() -> None:
    provider = create_razorpay_payment_link_provider(
        Settings(
            razorpay_key_id=SecretStr("rzp_test_key"),
            razorpay_key_secret=SecretStr("test-secret"),
        ),
    )

    assert provider is not None
    assert "test-secret" not in repr(provider)
