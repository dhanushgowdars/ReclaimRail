from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt, PaymentStateTransition
from app.db.models.payment_lab import (
    PaymentLabRun,
    PaymentLabRunMode,
    PaymentLabRunProvenance,
    PaymentLabRunStatus,
)
from app.db.models.recovery import RecoveryCase
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.payments import PaymentState
from app.services.payment_webhook_processor import (
    PaymentWebhookDisposition,
    process_canonical_payment_webhook,
)

PAYMENT_CREATED_TIMESTAMP = 1_787_550_000
EVENT_TIMESTAMP = 1_787_550_120
PROCESSED_AT = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_signed_failure_atomically_links_provider_order_to_lab_run() -> None:
    settings = get_settings()

    if settings.database_url is None:
        pytest.skip("Database URL is not configured")

    database_url = settings.database_url.get_secret_value()

    if not database_url:
        pytest.skip("Database URL is empty")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    unique_suffix = uuid4().hex
    run_id = uuid4()
    webhook_id = uuid4()
    provider_order_id = f"order_lab_correlation_{unique_suffix}"
    provider_payment_id = f"pay_lab_correlation_{unique_suffix}"
    provider_event_id = f"evt_lab_correlation_{unique_suffix}"
    payment_attempt_id: UUID | None = None

    payment_lab_run = PaymentLabRun(
        id=run_id,
        client_request_id=uuid4(),
        mode=PaymentLabRunMode.GUIDED.value,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        status=PaymentLabRunStatus.CHECKOUT_READY.value,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        receipt=f"rrlab_{unique_suffix[:24]}",
        provider_order_id=provider_order_id,
        provider_order_status="created",
        provider_created_at=PROCESSED_AT - timedelta(minutes=1),
        payment_attempt_id=None,
        failure_code=None,
        checkout_expires_at=PROCESSED_AT + timedelta(minutes=9),
        created_at=PROCESSED_AT - timedelta(minutes=1),
        updated_at=PROCESSED_AT - timedelta(minutes=1),
        version=1,
    )
    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_payment_lab_correlation",
        provider_created_at=datetime.fromtimestamp(EVENT_TIMESTAMP, tz=UTC),
        payload={
            "entity": "event",
            "account_id": "acc_payment_lab_correlation",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": provider_payment_id,
                        "entity": "payment",
                        "amount": 349_900,
                        "currency": "INR",
                        "status": "failed",
                        "order_id": provider_order_id,
                        "method": "netbanking",
                        "created_at": PAYMENT_CREATED_TIMESTAMP,
                        "error_code": "BAD_REQUEST_ERROR",
                        "error_description": "Payment declined",
                        "error_source": "bank",
                        "error_step": "payment_authorization",
                        "error_reason": "payment_failed",
                    },
                },
            },
            "created_at": EVENT_TIMESTAMP,
        },
        payload_sha256="f" * 64,
        processing_status=WebhookProcessingStatus.RECEIVED.value,
        delivery_count=1,
        first_received_at=PROCESSED_AT,
        last_received_at=PROCESSED_AT,
        processed_at=None,
    )

    try:
        async with session_factory() as session, session.begin():
            session.add_all([payment_lab_run, webhook])

        async with session_factory() as session, session.begin():
            first_result = await process_canonical_payment_webhook(
                session,
                webhook_id,
                processed_at=PROCESSED_AT,
            )

            assert first_result.disposition is PaymentWebhookDisposition.PROJECTED

        async with session_factory() as session:
            stored_run = await session.get(PaymentLabRun, run_id)
            assert stored_run is not None
            assert stored_run.payment_attempt_id is not None
            payment_attempt_id = stored_run.payment_attempt_id
            assert stored_run.status == PaymentLabRunStatus.PAYMENT_ATTEMPTED.value
            assert stored_run.failure_code == "BAD_REQUEST_ERROR"
            assert stored_run.version == 2

            stored_attempt = await session.get(
                PaymentAttempt,
                payment_attempt_id,
            )
            assert stored_attempt is not None
            assert stored_attempt.provider_payment_id == provider_payment_id
            assert stored_attempt.provider_order_id == provider_order_id
            assert stored_attempt.current_state == PaymentState.FAILED.value
            assert stored_attempt.recovery_eligible is True

        async with session_factory() as session, session.begin():
            replay_result = await process_canonical_payment_webhook(
                session,
                webhook_id,
                processed_at=PROCESSED_AT + timedelta(seconds=1),
            )

            assert replay_result.disposition is PaymentWebhookDisposition.DUPLICATE

        async with session_factory() as session:
            replayed_run = await session.get(PaymentLabRun, run_id)
            assert replayed_run is not None
            assert replayed_run.version == 2
    finally:
        try:
            async with session_factory() as cleanup_session, cleanup_session.begin():
                await cleanup_session.execute(
                    delete(PaymentLabRun).where(PaymentLabRun.id == run_id),
                )
                # A live recovery worker may legitimately open a case for this
                # integration test's failed payment before cleanup runs. Remove
                # that dependent projection before deleting its payment attempt.
                await cleanup_session.execute(
                    delete(RecoveryCase).where(
                        RecoveryCase.payment_attempt_id == payment_attempt_id,
                    ),
                )
                await cleanup_session.execute(
                    delete(PaymentStateTransition).where(
                        PaymentStateTransition.webhook_event_id == webhook_id,
                    ),
                )
                await cleanup_session.execute(
                    delete(PaymentAttempt).where(
                        PaymentAttempt.provider == "razorpay",
                        PaymentAttempt.provider_payment_id == provider_payment_id,
                    ),
                )
                await cleanup_session.execute(
                    delete(WebhookEvent).where(WebhookEvent.id == webhook_id),
                )
        finally:
            await engine.dispose()
