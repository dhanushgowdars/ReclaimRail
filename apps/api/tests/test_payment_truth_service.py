from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.domain.recovery.contracts import PaymentEvidenceSource
from app.services import payment_truth_service
from app.services.payment_truth_service import (
    PaymentEvidenceWrite,
    _invalidate_stale_recovery_plan,
    canonical_sha256,
    record_linked_runtime_evidence,
)

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


@pytest.mark.asyncio
async def test_linked_runtime_collector_records_merchant_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = MagicMock()
    attempt.id = ATTEMPT_ID
    attempt.current_state = "failed"
    attempt.state_version = 3
    attempt.provider_payment_id = "pay_runtime"
    attempt.provider_order_id = "order_runtime"
    session = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value = []
    no_case = MagicMock()
    no_case.scalar_one_or_none.return_value = None
    session.execute.side_effect = [empty, no_case]
    recorder = AsyncMock()
    monkeypatch.setattr(payment_truth_service, "record_payment_evidence", recorder)

    await record_linked_runtime_evidence(
        session,
        payment_attempt=attempt,
        observed_at=NOW,
    )

    request = recorder.await_args.args[1]
    assert request.source is PaymentEvidenceSource.MERCHANT_DATABASE
    assert request.fact_name == "payment.status"
    assert request.fact_value == "failed"
    assert request.normalized_fields["version"] == 3


@pytest.mark.asyncio
async def test_new_truth_invalidates_stale_recovery_work() -> None:
    recovery_case = MagicMock()
    recovery_case.id = UUID("20000000-0000-0000-0000-000000000001")
    recovery_case.version = 4
    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = recovery_case
    session = AsyncMock()
    session.execute.side_effect = [first_result, MagicMock(), MagicMock(), MagicMock()]

    await _invalidate_stale_recovery_plan(
        session,
        payment_attempt_id=ATTEMPT_ID,
        new_truth_version=5,
        resolved_at=NOW,
    )

    assert recovery_case.version == 5
    assert session.execute.await_count == 4
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "UPDATE recovery_agent_runs" in statements[1]
    assert "UPDATE recovery_actions" in statements[2]
    assert "UPDATE recovery_approvals" in statements[3]

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
