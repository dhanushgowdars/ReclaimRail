import json

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import Settings

RESEND_API_BASE_URL = "https://api.resend.com"
RESEND_EMAIL_PATH = "/emails"
RESEND_DEMO_SENDER = "ReclaimRail <onboarding@resend.dev>"


class ResendRecoveryEmailResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str


class ResendRecoveryEmailError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ResendRecoveryEmailProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = RESEND_API_BASE_URL,
        timeout_seconds: float = 10.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

        if not self._api_key:
            raise ValueError("Resend API key cannot be empty")
        if not self._base_url.startswith("https://"):
            raise ValueError("Resend API base URL must use HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("Resend email timeout must be positive")

    async def send_recovery_email(
        self,
        *,
        recipient: str,
        payment_link_url: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> ResendRecoveryEmailResult:
        normalized_recipient = recipient.strip()
        normalized_url = payment_link_url.strip()
        normalized_idempotency_key = idempotency_key.strip()
        if not normalized_recipient:
            raise ValueError("Resend recovery email recipient cannot be empty")
        if not normalized_url.startswith("https://"):
            raise ValueError("Payment Link URL must use HTTPS")
        if not normalized_idempotency_key:
            raise ValueError("Resend recovery email idempotency key cannot be empty")
        if len(normalized_idempotency_key) > 256:
            raise ValueError("Resend recovery email idempotency key cannot exceed 256 characters")

        amount = amount_minor / 100
        payload = {
            "from": RESEND_DEMO_SENDER,
            "to": [normalized_recipient],
            "subject": "Complete your ReclaimRail recovery payment",
            "text": (
                f"A payment of {currency.upper()} {amount:,.2f} was not completed. "
                f"Use this secure Razorpay Test Mode link to retry: {normalized_url}\n\n"
                "This is a controlled ReclaimRail recovery demonstration."
            ),
        }

        try:
            async with httpx2.AsyncClient(
                base_url=self._base_url,
                timeout=httpx2.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    RESEND_EMAIL_PATH,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                        "Idempotency-Key": normalized_idempotency_key,
                    },
                    json=payload,
                )
        except httpx2.RequestError as error:
            raise ResendRecoveryEmailError(
                f"Resend recovery email request failed: {type(error).__name__}",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            raise ResendRecoveryEmailError(
                "Resend rejected the recovery email",
                retryable=response.status_code == 429 or response.status_code >= 500,
                status_code=response.status_code,
            )

        try:
            return ResendRecoveryEmailResult.model_validate(json.loads(response.content))
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise ResendRecoveryEmailError(
                "Resend returned an invalid recovery-email response",
                retryable=False,
                status_code=response.status_code,
            ) from error


def create_resend_recovery_email_provider(
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> ResendRecoveryEmailProvider | None:
    api_secret = getattr(settings, "resend_api_key", None)
    if api_secret is None:
        return None
    api_key = api_secret.get_secret_value().strip()
    if not api_key:
        return None
    return ResendRecoveryEmailProvider(api_key=api_key, transport=transport)
