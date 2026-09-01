import json

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.resend.recovery_email import (
    ResendRecoveryEmailError,
    ResendRecoveryEmailProvider,
    create_resend_recovery_email_provider,
)


@pytest.mark.asyncio
async def test_sends_direct_recovery_email_with_bearer_auth() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.resend.test/emails"
        assert request.headers["Authorization"] == "Bearer re_test_key"
        assert request.headers["Idempotency-Key"] == "recovery-message/test-001"
        payload = json.loads(request.content)
        assert payload["to"] == ["demo@example.com"]
        assert "https://rzp.io/i/test" in payload["text"]
        return httpx2.Response(200, request=request, json={"id": "email_001"})

    provider = ResendRecoveryEmailProvider(
        api_key="re_test_key",
        base_url="https://api.resend.test",
        transport=httpx2.MockTransport(handler),
    )

    result = await provider.send_recovery_email(
        recipient=" demo@example.com ",
        payment_link_url="https://rzp.io/i/test",
        amount_minor=349_900,
        currency="inr",
        idempotency_key=" recovery-message/test-001 ",
    )

    assert result.id == "email_001"


@pytest.mark.asyncio
async def test_classifies_resend_rate_limit_as_retryable() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, request=request, json={"message": "limited"})

    provider = ResendRecoveryEmailProvider(
        api_key="re_test_key",
        base_url="https://api.resend.test",
        transport=httpx2.MockTransport(handler),
    )

    with pytest.raises(ResendRecoveryEmailError) as error:
        await provider.send_recovery_email(
            recipient="demo@example.com",
            payment_link_url="https://rzp.io/i/test",
            amount_minor=349_900,
            currency="INR",
            idempotency_key="recovery-message/test-rate-limit",
        )

    assert error.value.retryable is True
    assert error.value.status_code == 429


def test_configuration_creates_provider_only_when_key_is_present() -> None:
    assert create_resend_recovery_email_provider(Settings(_env_file=None)) is None

    provider = create_resend_recovery_email_provider(
        Settings(resend_api_key=SecretStr("re_test_key")),
    )

    assert provider is not None
