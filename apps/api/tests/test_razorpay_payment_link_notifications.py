import base64

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.razorpay.payment_link_notifications import (
    RazorpayPaymentLinkNotificationError,
    RazorpayPaymentLinkNotificationMedium,
    RazorpayPaymentLinkNotificationProvider,
    create_razorpay_payment_link_notification_provider,
)


def create_provider(
    handler: httpx2.AsyncBaseTransport,
) -> RazorpayPaymentLinkNotificationProvider:
    return RazorpayPaymentLinkNotificationProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
        transport=handler,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "medium",
    [
        RazorpayPaymentLinkNotificationMedium.EMAIL,
        RazorpayPaymentLinkNotificationMedium.SMS,
    ],
)
async def test_sends_notification_with_basic_auth(
    medium: RazorpayPaymentLinkNotificationMedium,
) -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        assert request.method == "POST"
        assert str(request.url) == (
            f"https://api.razorpay.test/v1/payment_links/plink_test_001/notify_by/{medium.value}"
        )

        encoded_credentials = request.headers["Authorization"].removeprefix("Basic ")

        assert (
            base64.b64decode(
                encoded_credentials,
            ).decode()
            == "rzp_test_key:test-secret"
        )

        return httpx2.Response(
            200,
            request=request,
            json={"success": True},
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    result = await provider.send_notification(
        payment_link_id=" plink_test_001 ",
        medium=medium,
    )

    assert result.success is True


@pytest.mark.parametrize(
    "payment_link_id",
    [" ", "x" * 129],
)
@pytest.mark.asyncio
async def test_rejects_invalid_payment_link_id(
    payment_link_id: str,
) -> None:
    provider = RazorpayPaymentLinkNotificationProvider(
        key_id="rzp_test_key",
        key_secret="test-secret",
        base_url="https://api.razorpay.test",
    )

    with pytest.raises(ValueError):
        await provider.send_notification(
            payment_link_id=payment_link_id,
            medium=(RazorpayPaymentLinkNotificationMedium.EMAIL),
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
                "error": "sensitive-provider-message",
            },
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentLinkNotificationError,
    ) as caught:
        await provider.send_notification(
            payment_link_id="plink_test_001",
            medium=(RazorpayPaymentLinkNotificationMedium.EMAIL),
        )

    assert caught.value.retryable is retryable
    assert caught.value.status_code == status_code
    assert "sensitive-provider-message" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"success": False},
        {"success": "invalid"},
    ],
)
@pytest.mark.asyncio
async def test_rejects_unconfirmed_notification_response(
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
        RazorpayPaymentLinkNotificationError,
    ) as caught:
        await provider.send_notification(
            payment_link_id="plink_test_001",
            medium=(RazorpayPaymentLinkNotificationMedium.EMAIL),
        )

    assert caught.value.retryable is False
    assert caught.value.status_code == 200


@pytest.mark.asyncio
async def test_classifies_transport_failure_as_retryable() -> None:
    async def handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        raise httpx2.ConnectError(
            "sensitive transport failure",
            request=request,
        )

    provider = create_provider(
        httpx2.MockTransport(handler),
    )

    with pytest.raises(
        RazorpayPaymentLinkNotificationError,
    ) as caught:
        await provider.send_notification(
            payment_link_id="plink_test_001",
            medium=RazorpayPaymentLinkNotificationMedium.SMS,
        )

    assert caught.value.retryable is True
    assert caught.value.status_code is None
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
        create_razorpay_payment_link_notification_provider(
            Settings(
                _env_file=None,
                razorpay_key_id=None,
                razorpay_key_secret=None,
            ),
        )
        is None
    )

    assert (
        create_razorpay_payment_link_notification_provider(
            Settings(
                _env_file=None,
                razorpay_key_id=SecretStr("rzp_test_key"),
                razorpay_key_secret=None,
            ),
        )
        is None
    )


def test_factory_does_not_expose_key_secret() -> None:
    provider = create_razorpay_payment_link_notification_provider(
        Settings(
            _env_file=None,
            razorpay_key_id=SecretStr("rzp_test_key"),
            razorpay_key_secret=SecretStr("test-secret"),
        ),
    )

    assert provider is not None
    assert "test-secret" not in repr(provider)
