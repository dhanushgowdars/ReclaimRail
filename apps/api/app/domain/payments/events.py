from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.payments.state_machine import PaymentState


@dataclass(frozen=True, slots=True)
class PaymentLifecycleEvent:
    webhook_event_id: UUID
    provider_event_id: str
    provider: str
    account_id: str | None
    event_type: str

    payment_id: str
    order_id: str | None
    state: PaymentState

    amount_minor: int
    currency: str
    method: str | None

    event_created_at: datetime
    payment_created_at: datetime

    error_code: str | None
    error_description: str | None
    error_source: str | None
    error_step: str | None
    error_reason: str | None
