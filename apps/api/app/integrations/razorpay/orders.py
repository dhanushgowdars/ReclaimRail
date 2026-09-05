import json
from enum import StrEnum
from typing import Final

import httpx2
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.core.config import Settings

RAZORPAY_API_BASE_URL: Final = "https://api.razorpay.com"
RAZORPAY_ORDERS_PATH: Final = "/v1/orders"


class RazorpayOrderStatus(StrEnum):
    CREATED = "created"
    ATTEMPTED = "attempted"
    PAID = "paid"


class RazorpayOrderPaymentStatus(StrEnum):
    FAILED = "failed"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"


class RazorpayOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    amount_minor: int = Field(ge=10)
    currency: str = Field(min_length=3, max_length=3)
    receipt: str = Field(min_length=1, max_length=40)
    notes: dict[str, str] = Field(default_factory=dict, max_length=15)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("receipt")
    @classmethod
    def normalize_receipt(cls, value: str) -> str:
        if not value:
            raise ValueError("Razorpay order receipt cannot be empty")

        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}

        for raw_key, raw_value in value.items():
            key = raw_key.strip()
            note_value = raw_value.strip()

            if not key or not note_value:
                raise ValueError("Razorpay order notes cannot be empty")

            if len(key) > 256 or len(note_value) > 256:
                raise ValueError(
                    "Razorpay order note keys and values cannot exceed 256 characters",
                )

            normalized[key] = note_value

        return normalized

    def to_provider_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "amount": self.amount_minor,
            "currency": self.currency,
            "receipt": self.receipt,
            "partial_payment": False,
        }

        if self.notes:
            payload["notes"] = self.notes

        return payload


class RazorpayOrder(BaseModel):
    """Sanitised provider order evidence; this model cannot carry PII."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    order_id: str = Field(alias="id", min_length=1, max_length=128)
    amount_minor: int = Field(alias="amount", gt=0)
    amount_paid_minor: int = Field(alias="amount_paid", ge=0)
    amount_due_minor: int = Field(alias="amount_due", ge=0)
    currency: str = Field(min_length=3, max_length=3)
    receipt: str = Field(min_length=1, max_length=40)
    status: RazorpayOrderStatus
    attempts: int = Field(ge=0)
    provider_created_at: int = Field(alias="created_at", ge=0)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class RazorpayOrderPayment(BaseModel):
    """Sanitised payment evidence fetched for one Razorpay Order."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)

    payment_id: str = Field(alias="id", min_length=1, max_length=128)
    amount_minor: int = Field(alias="amount", gt=0)
    currency: str = Field(min_length=3, max_length=3)
    status: RazorpayOrderPaymentStatus
    order_id: str = Field(min_length=1, max_length=128)
    method: str | None = Field(default=None, max_length=64)
    provider_created_at: int = Field(alias="created_at", ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    error_description: str | None = Field(default=None, max_length=1000)
    error_source: str | None = Field(default=None, max_length=128)
    error_step: str | None = Field(default=None, max_length=128)
    error_reason: str | None = Field(default=None, max_length=128)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class RazorpayOrderProviderError(RuntimeError):
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


class RazorpayOrderProvider:
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
            raise ValueError("Razorpay API timeout must be positive")

        self._key_id = normalized_key_id
        self._key_secret = normalized_key_secret
        self._base_url = normalized_base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def checkout_key_id(self) -> str:
        return self._key_id

    async def create_order(self, request: RazorpayOrderRequest) -> RazorpayOrder:
        try:
            async with httpx2.AsyncClient(
                base_url=self._base_url,
                auth=httpx2.BasicAuth(self._key_id, self._key_secret),
                timeout=httpx2.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    RAZORPAY_ORDERS_PATH,
                    json=request.to_provider_payload(),
                    headers={"Accept": "application/json"},
                )
        except httpx2.RequestError as error:
            raise RazorpayOrderProviderError(
                f"Razorpay Orders request failed: {type(error).__name__}",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500

            raise RazorpayOrderProviderError(
                "Razorpay Orders API rejected the request",
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            payload = json.loads(response.content)
            return RazorpayOrder.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise RazorpayOrderProviderError(
                "Razorpay Orders API returned an invalid response",
                retryable=False,
                status_code=response.status_code,
            ) from error

    async def fetch_order_payments(self, order_id: str) -> tuple[RazorpayOrderPayment, ...]:
        """Read Razorpay's current payment evidence for a known Test Mode Order."""

        normalized_order_id = order_id.strip()
        if not normalized_order_id:
            raise ValueError("Razorpay Order ID cannot be empty")

        try:
            async with httpx2.AsyncClient(
                base_url=self._base_url,
                auth=httpx2.BasicAuth(self._key_id, self._key_secret),
                timeout=httpx2.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.get(
                    f"{RAZORPAY_ORDERS_PATH}/{normalized_order_id}/payments",
                    headers={"Accept": "application/json"},
                )
        except httpx2.RequestError as error:
            raise RazorpayOrderProviderError(
                f"Razorpay Order payment verification failed: {type(error).__name__}",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            raise RazorpayOrderProviderError(
                "Razorpay Order payment verification was rejected",
                retryable=response.status_code == 429 or response.status_code >= 500,
                status_code=response.status_code,
            )

        try:
            payload = json.loads(response.content)
            items = payload["items"]
            if not isinstance(items, list):
                raise TypeError("items is not a list")
            return tuple(RazorpayOrderPayment.model_validate(item) for item in items)
        except (KeyError, json.JSONDecodeError, ValidationError, TypeError) as error:
            raise RazorpayOrderProviderError(
                "Razorpay Order payment verification returned an invalid response",
                retryable=False,
                status_code=response.status_code,
            ) from error


def create_razorpay_order_provider(
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> RazorpayOrderProvider | None:
    if settings.razorpay_key_id is None or settings.razorpay_key_secret is None:
        return None

    key_id = settings.razorpay_key_id.get_secret_value().strip()
    key_secret = settings.razorpay_key_secret.get_secret_value().strip()

    if not key_id or not key_secret:
        return None

    if not key_id.startswith("rzp_test_"):
        return None

    return RazorpayOrderProvider(
        key_id=key_id,
        key_secret=key_secret,
        transport=transport,
    )
