from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.webhook import (
    WebhookEvent,
    WebhookProcessingStatus,
)
from app.domain.payments import (
    PaymentState,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
)
from app.services import payment_webhook_processor
from app.services.payment_lab_webhook_correlation import (
    PaymentLabWebhookCorrelationError,
)
from app.services.payment_projector import PaymentProjectionResult
from app.services.payment_webhook_processor import (
    PaymentWebhookDisposition,
    PaymentWebhookEventNotFoundError,
    process_canonical_payment_webhook,
)
from app.services.recovery_outcome_reconciler import (
    RecoveryOutcomeReconciliationNotReadyError,
)

WEBHOOK_ID = UUID("60000000-0000-0000-0000-000000000001")
ATTEMPT_ID = UUID("70000000-0000-0000-0000-000000000001")

PROVIDER_CREATED_AT = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 8, 24, 8, 1, tzinfo=UTC)
PROCESSED_AT = datetime(2026, 8, 24, 8, 2, tzinfo=UTC)

PROVIDER_TIMESTAMP = 1_787_550_000


def valid_payment_payload(
    *,
    event_type: str = "payment.failed",
) -> dict[str, object]:
    status = event_type.removeprefix("payment.")

    return {
        "entity": "event",
        "account_id": "acc_processor_test",
        "event": event_type,
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_processor_test",
                    "entity": "payment",
                    "amount": 50_000,
                    "currency": "INR",
                    "status": status,
                    "order_id": "order_processor_test",
                    "method": "upi",
                    "created_at": PROVIDER_TIMESTAMP,
                    "error_code": ("BAD_REQUEST_ERROR" if event_type == "payment.failed" else None),
                    "error_description": (
                        "Payment declined" if event_type == "payment.failed" else None
                    ),
                },
            },
        },
        "created_at": PROVIDER_TIMESTAMP,
    }


def valid_payment_link_payload(
    *,
    event_type: str = "payment_link.paid",
) -> dict[str, object]:
    status = event_type.removeprefix("payment_link.")
    return {
        "entity": "event",
        "account_id": "acc_processor_test",
        "event": event_type,
        "contains": ["payment_link"],
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_processor_test",
                    "short_url": "https://rzp.io/i/processor-test",
                    "status": status,
                    "amount": 50_000,
                    "amount_paid": 50_000 if status == "paid" else 0,
                    "currency": "INR",
                    "reference_id": "rr_processor_test",
                    "updated_at": PROVIDER_TIMESTAMP,
                },
            },
        },
        "created_at": PROVIDER_TIMESTAMP,
    }


def make_webhook_event(
    *,
    event_type: str = "payment.failed",
    payload: dict[str, object] | None = None,
) -> WebhookEvent:
    return WebhookEvent(
        id=WEBHOOK_ID,
        provider="razorpay",
        provider_event_id="evt_processor_test",
        event_type=event_type,
        account_id="acc_processor_test",
        provider_created_at=PROVIDER_CREATED_AT,
        payload=payload
        or valid_payment_payload(
            event_type=event_type,
        ),
        payload_sha256="a" * 64,
        processing_status=WebhookProcessingStatus.RECEIVED.value,
        delivery_count=1,
        first_received_at=RECEIVED_AT,
        last_received_at=RECEIVED_AT,
        processed_at=None,
    )


def make_projection_result(
    *,
    duplicate: bool = False,
) -> PaymentProjectionResult:
    return PaymentProjectionResult(
        payment_attempt_id=ATTEMPT_ID,
        webhook_event_id=WEBHOOK_ID,
        state=PaymentState.FAILED,
        state_version=1,
        outcome=PaymentTransitionOutcome.APPLIED,
        reason=PaymentTransitionReason.INITIALIZED,
        duplicate=duplicate,
    )


def optional_scalar_result(
    value: WebhookEvent | None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.fixture(autouse=True)
def no_payment_lab_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_webhook_processor,
        "prepare_payment_lab_webhook_correlation",
        AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_projects_canonical_webhook_and_marks_it_processed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        webhook_event,
    )

    projector = AsyncMock(
        return_value=make_projection_result(),
    )
    monkeypatch.setattr(
        payment_webhook_processor,
        "project_payment_lifecycle_event",
        projector,
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.PROJECTED
    assert result.projection is not None
    assert result.error is None

    assert webhook_event.processing_status == (WebhookProcessingStatus.PROCESSED.value)
    assert webhook_event.processed_at == PROCESSED_AT

    normalized_event = projector.await_args.args[1]
    assert normalized_event.payment_id == "pay_processor_test"
    assert normalized_event.state is PaymentState.FAILED
    assert normalized_event.amount_minor == 50_000

    statement = session.execute.await_args.args[0]
    assert "FOR UPDATE" in str(statement)

    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_replayed_projection_returns_duplicate_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        webhook_event,
    )

    monkeypatch.setattr(
        payment_webhook_processor,
        "project_payment_lifecycle_event",
        AsyncMock(
            return_value=make_projection_result(
                duplicate=True,
            ),
        ),
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.DUPLICATE
    assert result.projection is not None
    assert webhook_event.processing_status == (WebhookProcessingStatus.PROCESSED.value)


@pytest.mark.asyncio
async def test_unsupported_webhook_is_skipped_without_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event(
        event_type="order.paid",
        payload={
            "entity": "event",
            "account_id": "acc_processor_test",
            "event": "order.paid",
            "contains": ["order"],
            "payload": {},
            "created_at": PROVIDER_TIMESTAMP,
        },
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        webhook_event,
    )

    projector = AsyncMock()
    monkeypatch.setattr(
        payment_webhook_processor,
        "project_payment_lifecycle_event",
        projector,
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.SKIPPED
    assert result.projection is None
    assert result.error is None
    assert webhook_event.processing_status == (WebhookProcessingStatus.PROCESSED.value)

    projector.assert_not_awaited()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_signed_payment_link_webhook_reconciles_owned_recovery_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event(
        event_type="payment_link.paid",
        payload=valid_payment_link_payload(),
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(webhook_event)
    reconciler = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(
        payment_webhook_processor,
        "reconcile_recovery_payment_link_webhook",
        reconciler,
    )
    projector = AsyncMock()
    monkeypatch.setattr(
        payment_webhook_processor,
        "project_payment_lifecycle_event",
        projector,
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.PROJECTED
    assert result.projection is None
    reconciler.assert_awaited_once()
    assert reconciler.await_args.kwargs["payment_link"].payment_link_id == "plink_processor_test"
    projector.assert_not_awaited()
    assert webhook_event.processing_status == WebhookProcessingStatus.PROCESSED.value


@pytest.mark.asyncio
async def test_unowned_payment_link_webhook_is_safely_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event(
        event_type="payment_link.paid",
        payload=valid_payment_link_payload(),
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(webhook_event)
    monkeypatch.setattr(
        payment_webhook_processor,
        "reconcile_recovery_payment_link_webhook",
        AsyncMock(return_value=None),
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.SKIPPED
    assert result.error is None


@pytest.mark.asyncio
async def test_out_of_order_payment_link_webhook_defers_to_polling_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event(
        event_type="payment_link.paid",
        payload=valid_payment_link_payload(),
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(webhook_event)
    monkeypatch.setattr(
        payment_webhook_processor,
        "reconcile_recovery_payment_link_webhook",
        AsyncMock(
            side_effect=RecoveryOutcomeReconciliationNotReadyError(
                "Recovery action is not committed yet",
            ),
        ),
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.SKIPPED
    assert result.error is None
    assert webhook_event.processing_status == WebhookProcessingStatus.PROCESSED.value
    assert webhook_event.processed_at == PROCESSED_AT
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_payment_payload_is_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event(
        payload={
            "entity": "event",
            "account_id": "acc_processor_test",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_processor_test",
                        "entity": "payment",
                        "status": "failed",
                    },
                },
            },
            "created_at": PROVIDER_TIMESTAMP,
        },
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        webhook_event,
    )

    projector = AsyncMock()
    monkeypatch.setattr(
        payment_webhook_processor,
        "project_payment_lifecycle_event",
        projector,
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.FAILED
    assert result.projection is None
    assert result.error is not None
    assert "invalid payment entity" in result.error.lower()

    assert webhook_event.processing_status == (WebhookProcessingStatus.FAILED.value)
    assert webhook_event.processed_at == PROCESSED_AT

    projector.assert_not_awaited()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_lab_identity_conflict_fails_before_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_event = make_webhook_event()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(
        webhook_event,
    )
    projector = AsyncMock()

    monkeypatch.setattr(
        payment_webhook_processor,
        "prepare_payment_lab_webhook_correlation",
        AsyncMock(
            side_effect=PaymentLabWebhookCorrelationError(
                "Payment Lab webhook amount does not match the provider Order",
            ),
        ),
    )
    monkeypatch.setattr(
        payment_webhook_processor,
        "project_payment_lifecycle_event",
        projector,
    )

    result = await process_canonical_payment_webhook(
        session,
        WEBHOOK_ID,
        processed_at=PROCESSED_AT,
    )

    assert result.disposition is PaymentWebhookDisposition.FAILED
    assert result.projection is None
    assert result.error is not None
    assert "amount" in result.error
    assert webhook_event.processing_status == WebhookProcessingStatus.FAILED.value
    projector.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_canonical_webhook_is_rejected() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(None)

    with pytest.raises(
        PaymentWebhookEventNotFoundError,
        match=str(WEBHOOK_ID),
    ):
        await process_canonical_payment_webhook(
            session,
            WEBHOOK_ID,
            processed_at=PROCESSED_AT,
        )

    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()
