from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.recovery.contracts import PaymentEvidenceSource
from app.services.payment_truth_service import PaymentEvidenceWrite, canonical_sha256

ATTEMPT_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)


def test_canonical_sha256_is_stable_across_mapping_order() -> None:
    assert canonical_sha256({"state": "failed", "amount": 500}) == canonical_sha256(
        {"amount": 500, "state": "failed"},
    )


def test_evidence_write_normalizes_digest_and_rejects_naive_time() -> None:
    request = PaymentEvidenceWrite(
        payment_attempt_id=ATTEMPT_ID,
        source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
        source_reference="evt_1",
        fact_name="payment.status",
        fact_value="failed",
        content_sha256="A" * 64,
        observed_at=NOW,
        verified=True,
    )
    assert request.content_sha256 == "a" * 64

    with pytest.raises(ValueError, match="timezone-aware"):
        PaymentEvidenceWrite(
            payment_attempt_id=ATTEMPT_ID,
            source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
            source_reference="evt_1",
            fact_name="payment.status",
            fact_value="failed",
            content_sha256="a" * 64,
            observed_at=datetime(2026, 9, 22, 3, 0),
            verified=True,
        )

    with pytest.raises(ValueError, match="must follow"):
        PaymentEvidenceWrite(
            payment_attempt_id=ATTEMPT_ID,
            source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
            source_reference="evt_1",
            fact_name="payment.status",
            fact_value="failed",
            content_sha256="a" * 64,
            observed_at=NOW,
            fresh_until=NOW - timedelta(seconds=1),
            verified=True,
        )
