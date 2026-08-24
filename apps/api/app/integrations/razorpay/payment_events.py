from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.domain.payments import (
    PaymentLifecycleEvent,
    PaymentState,
)
from app.integrations.razorpay.webhooks import (
    RazorpayWebhookEnvelope,
)

EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
MAX_PROVIDER_TIMESTAMP: Final = 253_402_300_799

PAYMENT_EVENT_STATES: Final[Mapping[str, PaymentState]] = {
    "payment.authorized": PaymentState.AUTHORIZED,
    "payment.captured": PaymentState.CAPTURED,
    "payment.failed": PaymentState.FAILED,
    "payment.refunded": PaymentState.REFUNDED,
}


class PaymentEventNormalizationError(ValueError):
    pass


class UnsupportedPaymentEventError(
    PaymentEventNormalizationError,
):
    pass


class RazorpayPaymentEntity(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    entity: Literal["payment"]
    amount: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: str = Field(min_length=1, max_length=32)

    order_id: str | None = Field(
        default=None,
        max_length=128,
    )
    method: str | None = Field(
        default=None,
        max_length=64,
    )
    created_at: int | None = Field(
        default=None,
        ge=0,
        le=MAX_PROVIDER_TIMESTAMP,
    )

    error_code: str | None = Field(
        default=None,
        max_length=128,
    )
    error_description: str | None = Field(
        default=None,
        max_length=1000,
    )
    error_source: str | None = Field(
        default=None,
        max_length=128,
    )
    error_step: str | None = Field(
        default=None,
        max_length=128,
    )
    error_reason: str | None = Field(
        default=None,
        max_length=128,
    )

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


def timestamp_to_datetime(timestamp: int) -> datetime:
    return EPOCH + timedelta(seconds=timestamp)


def normalize_razorpay_payment_event(
    *,
    webhook_event_id: UUID,
    provider_event_id: str,
    envelope: RazorpayWebhookEnvelope,
) -> PaymentLifecycleEvent:
    expected_state = PAYMENT_EVENT_STATES.get(
        envelope.event,
    )

    if expected_state is None:
        raise UnsupportedPaymentEventError(
            f"Unsupported Razorpay payment event: {envelope.event}",
        )

    payment_wrapper = envelope.payload.get("payment")

    if not isinstance(payment_wrapper, dict):
        raise PaymentEventNormalizationError(
            "Webhook payload does not contain a payment object",
        )

    payment_payload = payment_wrapper.get("entity")

    if not isinstance(payment_payload, dict):
        raise PaymentEventNormalizationError(
            "Webhook payment object does not contain an entity",
        )

    try:
        payment = RazorpayPaymentEntity.model_validate(
            payment_payload,
        )
    except ValidationError as error:
        raise PaymentEventNormalizationError(
            "Webhook contains an invalid payment entity",
        ) from error

    try:
        provider_state = PaymentState(payment.status)
    except ValueError as error:
        raise PaymentEventNormalizationError(
            f"Unsupported Razorpay payment status: {payment.status}",
        ) from error

    if provider_state is not expected_state:
        raise PaymentEventNormalizationError(
            (
                "Webhook event and payment status do not match: "
                f"{envelope.event} != {payment.status}"
            ),
        )

    event_created_at = timestamp_to_datetime(
        envelope.created_at,
    )
    payment_created_at = timestamp_to_datetime(
        payment.created_at if payment.created_at is not None else envelope.created_at
    )

    return PaymentLifecycleEvent(
        webhook_event_id=webhook_event_id,
        provider_event_id=provider_event_id,
        provider="razorpay",
        account_id=envelope.account_id,
        event_type=envelope.event,
        payment_id=payment.id,
        order_id=payment.order_id,
        state=provider_state,
        amount_minor=payment.amount,
        currency=payment.currency,
        method=payment.method,
        event_created_at=event_created_at,
        payment_created_at=payment_created_at,
        error_code=payment.error_code,
        error_description=payment.error_description,
        error_source=payment.error_source,
        error_step=payment.error_step,
        error_reason=payment.error_reason,
    )
