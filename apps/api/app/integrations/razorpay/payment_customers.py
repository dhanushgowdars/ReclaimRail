import json
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings

RAZORPAY_API_BASE_URL = "https://api.razorpay.com"
RAZORPAY_PAYMENT_PATH = "/v1/payments"


class RazorpayPaymentCustomer(BaseModel):
    """Transient customer contact fetched from Razorpay.

    Email and contact are excluded from representations and serialization
    to reduce the risk of accidental logging or persistence.
    """

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    provider_payment_id: str = Field(
        alias="id",
        min_length=1,
        max_length=128,
    )
    email: str | None = Field(
        default=None,
        max_length=320,
        repr=False,
        exclude=True,
    )
    contact: str | None = Field(
        default=None,
        max_length=32,
        repr=False,
        exclude=True,
    )

    @field_validator("email", "contact", mode="before")
    @classmethod
    def normalize_optional_contact(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None

        return value

    @property
    def has_email(self) -> bool:
        return self.email is not None

    @property
    def has_contact(self) -> bool:
        return self.contact is not None


class RazorpayPaymentCustomerProviderError(RuntimeError):
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


class RazorpayPaymentCustomerProvider:
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
            raise ValueError("Razorpay customer lookup timeout must be positive")

        self._key_id = normalized_key_id
        self._key_secret = normalized_key_secret
        self._base_url = normalized_base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @staticmethod
    def _normalize_payment_id(
        provider_payment_id: str,
    ) -> str:
        normalized = provider_payment_id.strip()

        if not normalized:
            raise ValueError("Razorpay Payment ID cannot be empty")

        if len(normalized) > 128:
            raise ValueError(
                "Razorpay Payment ID cannot exceed 128 characters",
            )

        return normalized

    async def fetch_payment_customer(
        self,
        provider_payment_id: str,
    ) -> RazorpayPaymentCustomer:
        normalized_payment_id = self._normalize_payment_id(
            provider_payment_id,
        )
        encoded_payment_id = quote(
            normalized_payment_id,
            safe="",
        )

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
                response = await client.get(
                    f"{RAZORPAY_PAYMENT_PATH}/{encoded_payment_id}",
                    headers={"Accept": "application/json"},
                )
        except httpx2.RequestError as error:
            raise RazorpayPaymentCustomerProviderError(
                "Razorpay payment customer lookup failed",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500

            raise RazorpayPaymentCustomerProviderError(
                "Razorpay Payments API rejected the customer lookup",
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            payload = json.loads(response.content)
            customer = RazorpayPaymentCustomer.model_validate(payload)
        except (
            json.JSONDecodeError,
            ValidationError,
            TypeError,
        ) as error:
            raise RazorpayPaymentCustomerProviderError(
                "Razorpay Payments API returned an invalid customer response",
                retryable=False,
                status_code=response.status_code,
            ) from error

        if customer.provider_payment_id != normalized_payment_id:
            raise RazorpayPaymentCustomerProviderError(
                "Razorpay Payments API returned a mismatched payment",
                retryable=False,
                status_code=response.status_code,
            )

        return customer


def create_razorpay_payment_customer_provider(
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> RazorpayPaymentCustomerProvider | None:
    if settings.razorpay_key_id is None or settings.razorpay_key_secret is None:
        return None

    key_id = settings.razorpay_key_id.get_secret_value().strip()
    key_secret = settings.razorpay_key_secret.get_secret_value().strip()

    if not key_id or not key_secret:
        return None

    return RazorpayPaymentCustomerProvider(
        key_id=key_id,
        key_secret=key_secret,
        transport=transport,
    )
