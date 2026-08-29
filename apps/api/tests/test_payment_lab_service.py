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
    RazorpayOrder,
    RazorpayOrderProvider,
    RazorpayOrderStatus,
)
from app.services.payment_lab_service import (
    PaymentLabRunLimitError,
    build_payment_lab_receipt,
    create_payment_lab_run,
)

NOW = datetime(2026, 8, 26, 16, 0, tzinfo=UTC)
CLIENT_REQUEST_ID = UUID("10000000-0000-0000-0000-000000000001")
RUN_ID = UUID("20000000-0000-0000-0000-000000000001")


def scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


def build_session(*execute_values: object) -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=[scalar_result(value) for value in execute_values],
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def build_order(*, receipt: str) -> RazorpayOrder:
    return RazorpayOrder(
        id="order_test_001",
        amount=349_900,
        amount_paid=0,
        amount_due=349_900,
        currency="INR",
        receipt=receipt,
        status=RazorpayOrderStatus.CREATED,
        attempts=0,
        created_at=int(NOW.timestamp()),
    )


def build_ready_run() -> PaymentLabRun:
    return PaymentLabRun(
        id=RUN_ID,
        client_request_id=CLIENT_REQUEST_ID,
        mode=PaymentLabRunMode.GUIDED.value,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        status=PaymentLabRunStatus.CHECKOUT_READY.value,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        test_email_contact_consent=False,
        receipt=build_payment_lab_receipt(RUN_ID),
        provider_order_id="order_test_001",
        provider_order_status="created",
        checkout_expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
        updated_at=NOW,
    )


def common_kwargs() -> dict[str, object]:
    return {
        "client_request_id": CLIENT_REQUEST_ID,
        "mode": PaymentLabRunMode.GUIDED,
        "amount_minor": 349_900,
        "currency": "INR",
        "payment_method": "netbanking",
        "reference_time": NOW,
        "minimum_amount_minor": 100,
        "maximum_amount_minor": 5_000_000,
        "hourly_run_limit": 20,
        "maximum_active_runs": 5,
        "checkout_timeout_seconds": 600,
    }


@pytest.mark.asyncio
async def test_creates_reserved_test_order_and_marks_checkout_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_session(None, 0, 0)
    provider = MagicMock(spec=RazorpayOrderProvider)

    monkeypatch.setattr(
        "app.services.payment_lab_service.uuid4",
        lambda: RUN_ID,
    )
    provider.create_order = AsyncMock(
        return_value=build_order(receipt=build_payment_lab_receipt(RUN_ID)),
    )

    result = await create_payment_lab_run(
        session,
        provider=provider,
        **common_kwargs(),  # type: ignore[arg-type]
    )

    stored_run = session.add.call_args.args[0]

    assert result.payment_lab_run_id == RUN_ID
    assert result.provider_order_id == "order_test_001"
    assert result.created is True
    assert stored_run.status == PaymentLabRunStatus.CHECKOUT_READY.value
    assert stored_run.provenance == PaymentLabRunProvenance.RAZORPAY_TEST.value
    assert stored_run.failure_code is None
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_replays_ready_run_without_creating_duplicate_order() -> None:
    ready_run = build_ready_run()
    session = build_session(ready_run)
    provider = MagicMock(spec=RazorpayOrderProvider)
    provider.create_order = AsyncMock()

    result = await create_payment_lab_run(
        session,
        provider=provider,
        **common_kwargs(),  # type: ignore[arg-type]
    )

    assert result.created is False
    assert result.provider_order_id == "order_test_001"
    provider.create_order.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_run_when_hourly_limit_is_reached() -> None:
    session = build_session(None, 20)
    provider = MagicMock(spec=RazorpayOrderProvider)

    with pytest.raises(PaymentLabRunLimitError, match="hourly"):
        await create_payment_lab_run(
            session,
            provider=provider,
            **common_kwargs(),  # type: ignore[arg-type]
        )

    session.add.assert_not_called()


def test_receipt_is_unique_and_within_provider_limit() -> None:
    receipt = build_payment_lab_receipt(RUN_ID)

    assert receipt == "rr_lab_20000000000000000000000000000001"
    assert len(receipt) <= 40
