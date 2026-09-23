from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment_lab import (
    PaymentLabRun,
    PaymentLabRunMode,
    PaymentLabRunProvenance,
    PaymentLabRunStatus,
)
from app.integrations.razorpay.orders import (
    RazorpayOrderPayment,
    RazorpayOrderPaymentStatus,
    RazorpayOrderProvider,
)
from app.services import payment_lab_provider_verification
from app.services.payment_lab_provider_verification import _candidate_ids, _verify_one

RUN_ID = UUID("81000000-0000-0000-0000-000000000001")
ATTEMPT_ID = UUID("82000000-0000-0000-0000-000000000001")
REFERENCE_TIME = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)


def make_run() -> PaymentLabRun:
    return PaymentLabRun(
        id=RUN_ID,
        client_request_id=UUID("83000000-0000-0000-0000-000000000001"),
        mode=PaymentLabRunMode.GUIDED.value,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        status=PaymentLabRunStatus.RECOVERY_RUNNING.value,
        amount_minor=50_000,
        currency="INR",
        payment_method="upi",
        receipt="rrlab_reconciliation",
        provider_order_id="order_reconciliation",
        provider_order_status="attempted",
        provider_created_at=REFERENCE_TIME - timedelta(minutes=5),
        provider_evidence_source="signed_webhook",
        provider_evidence_checked_at=REFERENCE_TIME - timedelta(minutes=1),
        payment_attempt_id=ATTEMPT_ID,
        failure_code="BAD_REQUEST_ERROR",
        checkout_expires_at=REFERENCE_TIME - timedelta(minutes=1),
        created_at=REFERENCE_TIME - timedelta(minutes=5),
        updated_at=REFERENCE_TIME - timedelta(minutes=1),
        version=2,
    )


def scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_candidate_query_keeps_signed_webhook_attempts_under_reconciliation() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalars.return_value = [RUN_ID]
    session.execute.return_value = result

    candidate_ids = await _candidate_ids(
        session,
        reference_time=REFERENCE_TIME,
        batch_size=10,
    )

    assert candidate_ids == (RUN_ID,)
    statement = str(session.execute.await_args.args[0])
    assert "provider_evidence_source" not in statement
    assert "payment_attempt_id IS NOT NULL" in statement


@pytest.mark.asyncio
async def test_provider_authorization_after_signed_failure_is_projected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = make_run()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = scalar_result(run)
    session.scalar.return_value = None
    provider = MagicMock(spec=RazorpayOrderProvider)
    provider.fetch_order_payments = AsyncMock(
        return_value=(
            RazorpayOrderPayment.model_validate(
                {
                    "id": "pay_reconciliation",
                    "amount": 50_000,
                    "currency": "INR",
                    "status": RazorpayOrderPaymentStatus.AUTHORIZED.value,
                    "order_id": "order_reconciliation",
                    "method": "upi",
                    "created_at": int((REFERENCE_TIME - timedelta(seconds=30)).timestamp()),
                },
            ),
        ),
    )
    processor = AsyncMock()
    monkeypatch.setattr(
        payment_lab_provider_verification,
        "process_canonical_payment_webhook",
        processor,
    )

    outcome = await _verify_one(
        session,
        payment_lab_run_id=RUN_ID,
        provider=provider,
        reference_time=REFERENCE_TIME,
    )

    assert outcome == "projected"
    provider.fetch_order_payments.assert_awaited_once_with("order_reconciliation")
    processor.assert_awaited_once()
    session.add.assert_called_once()
    added_event = session.add.call_args.args[0]
    assert added_event.provider_event_id == "provider-api:pay_reconciliation:authorized"
    assert (
        added_event.payload["reclaimrail_evidence_source"]
        == payment_lab_provider_verification.PROVIDER_API_EVIDENCE_SOURCE
    )
    assert run.provider_evidence_checked_at == REFERENCE_TIME
    session.commit.assert_awaited_once()
