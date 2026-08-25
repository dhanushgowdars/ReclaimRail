import json
from enum import StrEnum
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import Settings

RAZORPAY_API_BASE_URL = "https://api.razorpay.com"
RAZORPAY_PAYMENT_LINK_PATH = "/v1/payment_links"


class RazorpayPaymentLinkNotificationMedium(StrEnum):
    EMAIL = "email"
    SMS = "sms"


class RazorpayPaymentLinkNotificationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool


class RazorpayPaymentLinkNotificationError(RuntimeError):
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


class RazorpayPaymentLinkNotificationProvider:
    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        base_url: str = RAZORPAY_API_BASE_URL,
        timeout_seconds: float = 10.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        normalized_key_id = key_id.strip()
        normalized_key_secret = key_secret.strip()
        normalized_base_url = base_url.strip().rstrip("/")

        if not normalized_key_id:
            raise ValueError("Razorpay Key ID cannot be empty")
        if not normalized_key_secret:
            raise ValueError("Razorpay Key Secret cannot be empty")
        if not normalized_base_url.startswith("https://"):
            raise ValueError("Razorpay API base URL must use HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("Razorpay notification timeout must be positive")

        self._key_id = normalized_key_id
        self._key_secret = normalized_key_secret
        self._base_url = normalized_base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @staticmethod
    def _normalize_payment_link_id(payment_link_id: str) -> str:
        normalized = payment_link_id.strip()

        if not normalized:
            raise ValueError("Razorpay Payment Link ID cannot be empty")
        if len(normalized) > 128:
            raise ValueError(
                "Razorpay Payment Link ID cannot exceed 128 characters",
            )

        return normalized

    async def send_notification(
        self,
        *,
        payment_link_id: str,
        medium: RazorpayPaymentLinkNotificationMedium,
    ) -> RazorpayPaymentLinkNotificationResult:
        normalized_payment_link_id = self._normalize_payment_link_id(
            payment_link_id,
        )
        encoded_payment_link_id = quote(
            normalized_payment_link_id,
            safe="",
        )
        path = f"{RAZORPAY_PAYMENT_LINK_PATH}/{encoded_payment_link_id}/notify_by/{medium.value}"

        try:
            async with httpx2.AsyncClient(
                base_url=self._base_url,
                auth=httpx2.BasicAuth(
                    self._key_id,
                    self._key_secret,
                ),
                timeout=httpx2.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    path,
                    headers={"Accept": "application/json"},
                )
        except httpx2.RequestError as error:
            raise RazorpayPaymentLinkNotificationError(
                f"Razorpay notification request failed: {type(error).__name__}",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise RazorpayPaymentLinkNotificationError(
                "Razorpay Payment Links API rejected the notification",
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            payload = json.loads(response.content)
            result = RazorpayPaymentLinkNotificationResult.model_validate(
                payload,
            )
        except (
            json.JSONDecodeError,
            ValidationError,
            TypeError,
        ) as error:
            raise RazorpayPaymentLinkNotificationError(
                ("Razorpay Payment Links API returned an invalid notification response"),
                retryable=False,
                status_code=response.status_code,
            ) from error

        if not result.success:
            raise RazorpayPaymentLinkNotificationError(
                ("Razorpay Payment Links API did not confirm the notification"),
                retryable=False,
                status_code=response.status_code,
            )

        return result


def create_razorpay_payment_link_notification_provider(
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> RazorpayPaymentLinkNotificationProvider | None:
    if settings.razorpay_key_id is None or settings.razorpay_key_secret is None:
        return None

    key_id = settings.razorpay_key_id.get_secret_value().strip()
    key_secret = settings.razorpay_key_secret.get_secret_value().strip()

    if not key_id or not key_secret:
        return None

    return RazorpayPaymentLinkNotificationProvider(
        key_id=key_id,
        key_secret=key_secret,
        transport=transport,
    )
