import json
from datetime import datetime
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
RAZORPAY_PAYMENT_LINK_PATH: Final = "/v1/payment_links"


class RazorpayPaymentLinkStatus(StrEnum):
    CREATED = "created"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class RazorpayPaymentLinkRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    reference_id: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=2048)
    expire_by: datetime | None = None
    notes: dict[str, str] = Field(
        default_factory=dict,
        max_length=15,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("reference_id", "description")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Value cannot be empty")

        return value

    @field_validator("expire_by")
    @classmethod
    def require_aware_expiry(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Payment-link expiry must be timezone-aware")

        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}

        for raw_key, raw_value in value.items():
            key = raw_key.strip()
            note_value = raw_value.strip()

            if not key or not note_value:
                raise ValueError("Payment-link notes cannot contain empty keys or values")

            if len(key) > 256 or len(note_value) > 256:
                raise ValueError("Payment-link note keys and values cannot exceed 256 characters")

            normalized[key] = note_value

        return normalized

    def to_provider_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "amount": self.amount_minor,
            "currency": self.currency,
            "accept_partial": False,
            "reference_id": self.reference_id,
            "description": self.description,
            "reminder_enable": False,
        }

        if self.expire_by is not None:
            payload["expire_by"] = int(self.expire_by.timestamp())

        if self.notes:
            payload["notes"] = self.notes

        return payload


class RazorpayPaymentLink(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    payment_link_id: str = Field(
        alias="id",
        min_length=1,
        max_length=128,
    )
    short_url: str = Field(
        min_length=1,
        max_length=2048,
    )
    status: RazorpayPaymentLinkStatus
    amount_minor: int = Field(
        alias="amount",
        gt=0,
    )
    currency: str = Field(
        min_length=3,
        max_length=3,
    )
    reference_id: str = Field(
        min_length=1,
        max_length=40,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class RazorpayPaymentLinkProviderError(RuntimeError):
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


class RazorpayPaymentLinkProvider:
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

    async def create_payment_link(
        self,
        request: RazorpayPaymentLinkRequest,
    ) -> RazorpayPaymentLink:
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
                    RAZORPAY_PAYMENT_LINK_PATH,
                    json=request.to_provider_payload(),
                    headers={"Accept": "application/json"},
                )
        except httpx2.RequestError as error:
            raise RazorpayPaymentLinkProviderError(
                f"Razorpay Payment Links request failed: {type(error).__name__}",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500

            raise RazorpayPaymentLinkProviderError(
                "Razorpay Payment Links API rejected the request",
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            response_payload = json.loads(response.content)

            return RazorpayPaymentLink.model_validate(response_payload)
        except (
            json.JSONDecodeError,
            ValidationError,
            TypeError,
        ) as error:
            raise RazorpayPaymentLinkProviderError(
                "Razorpay Payment Links API returned an invalid response",
                retryable=False,
                status_code=response.status_code,
            ) from error


def create_razorpay_payment_link_provider(
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> RazorpayPaymentLinkProvider | None:
    if settings.razorpay_key_id is None or settings.razorpay_key_secret is None:
        return None

    key_id = settings.razorpay_key_id.get_secret_value().strip()
    key_secret = settings.razorpay_key_secret.get_secret_value().strip()

    if not key_id or not key_secret:
        return None

    return RazorpayPaymentLinkProvider(
        key_id=key_id,
        key_secret=key_secret,
        transport=transport,
    )
