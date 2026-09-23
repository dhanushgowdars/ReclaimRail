from datetime import UTC, datetime, timedelta

import pytest

from app.domain.payments import (
    PaymentDeliveryClassification,
    PaymentTransitionReason,
    classify_payment_event_reliability,
)
from app.domain.recovery.contracts import PaymentEvidenceSource

EVENT_AT = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("source", "reason", "delay", "expected"),
    [
        (
            PaymentEvidenceSource.VERIFIED_WEBHOOK,
            PaymentTransitionReason.PROGRESSED,
            timedelta(seconds=20),
            PaymentDeliveryClassification.ON_TIME,
        ),
        (
            PaymentEvidenceSource.VERIFIED_WEBHOOK,
            PaymentTransitionReason.PROGRESSED,
            timedelta(minutes=4),
            PaymentDeliveryClassification.DELAYED,
        ),
        (
            PaymentEvidenceSource.VERIFIED_WEBHOOK,
            PaymentTransitionReason.REGRESSION_BLOCKED,
            timedelta(seconds=10),
            PaymentDeliveryClassification.REORDERED,
        ),
        (
            PaymentEvidenceSource.PROVIDER_PAYMENT_API,
            PaymentTransitionReason.LATE_AUTHORIZATION,
            timedelta(minutes=10),
            PaymentDeliveryClassification.PROVIDER_RECONCILED,
        ),
        (
            PaymentEvidenceSource.VERIFIED_WEBHOOK,
            PaymentTransitionReason.PROGRESSED,
            timedelta(days=8),
            PaymentDeliveryClassification.STALE,
        ),
    ],
)
def test_classifies_event_delivery_with_explicit_provenance(
    source: PaymentEvidenceSource,
    reason: PaymentTransitionReason,
    delay: timedelta,
    expected: PaymentDeliveryClassification,
) -> None:
    reliability = classify_payment_event_reliability(
        evidence_source=source,
        transition_reason=reason,
        event_created_at=EVENT_AT,
        processed_at=EVENT_AT + delay,
    )

    assert reliability.evidence_source == source.value
    assert reliability.classification is expected
    assert reliability.delivery_latency_ms == int(delay.total_seconds() * 1000)


def test_clock_skew_never_creates_negative_delivery_latency() -> None:
    reliability = classify_payment_event_reliability(
        evidence_source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
        transition_reason=PaymentTransitionReason.INITIALIZED,
        event_created_at=EVENT_AT,
        processed_at=EVENT_AT - timedelta(seconds=5),
    )

    assert reliability.delivery_latency_ms == 0
    assert reliability.classification is PaymentDeliveryClassification.ON_TIME


def test_rejects_naive_event_times() -> None:
    with pytest.raises(ValueError, match="event_created_at"):
        classify_payment_event_reliability(
            evidence_source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
            transition_reason=PaymentTransitionReason.INITIALIZED,
            event_created_at=datetime(2026, 9, 22, 10, 0),
            processed_at=EVENT_AT,
        )
