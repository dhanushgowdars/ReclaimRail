"""Deterministic payment-event reliability classification."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.payments.state_machine import PaymentTransitionReason

PROVIDER_API_EVIDENCE_LABEL = "razorpay_api_verification"
DEFAULT_DELAY_THRESHOLD = timedelta(minutes=2)
MAX_EVENT_AGE = timedelta(days=7)


class PaymentDeliveryClassification(StrEnum):
    ON_TIME = "on_time"
    DELAYED = "delayed"
    REORDERED = "reordered"
    PROVIDER_RECONCILED = "provider_reconciled"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class PaymentEventReliability:
    evidence_source: str
    classification: PaymentDeliveryClassification
    delivery_latency_ms: int


def classify_payment_event_reliability(
    *,
    evidence_source: str,
    transition_reason: PaymentTransitionReason,
    event_created_at: datetime,
    processed_at: datetime,
    delay_threshold: timedelta = DEFAULT_DELAY_THRESHOLD,
) -> PaymentEventReliability:
    """Classify persisted evidence without asking an LLM to infer chronology."""
    for field_name, value in (
        ("event_created_at", event_created_at),
        ("processed_at", processed_at),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")
    if delay_threshold <= timedelta(0):
        raise ValueError("delay_threshold must be positive")

    latency = max(processed_at - event_created_at, timedelta(0))
    latency_ms = int(latency.total_seconds() * 1000)

    normalized_source = str(evidence_source).strip()
    if not normalized_source:
        raise ValueError("evidence_source cannot be empty")

    if latency > MAX_EVENT_AGE:
        classification = PaymentDeliveryClassification.STALE
    elif transition_reason in {
        PaymentTransitionReason.REGRESSION_BLOCKED,
        PaymentTransitionReason.TERMINAL_STATE,
    }:
        classification = PaymentDeliveryClassification.REORDERED
    elif normalized_source == "provider_payment_api":
        classification = PaymentDeliveryClassification.PROVIDER_RECONCILED
    elif latency > delay_threshold:
        classification = PaymentDeliveryClassification.DELAYED
    else:
        classification = PaymentDeliveryClassification.ON_TIME

    return PaymentEventReliability(
        evidence_source=normalized_source,
        classification=classification,
        delivery_latency_ms=latency_ms,
    )
