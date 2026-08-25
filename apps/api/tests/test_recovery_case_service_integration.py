import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import RecoveryAuditEvent, RecoveryCase
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.services.recovery_audit_store import verify_persisted_recovery_audit_chain
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    RecoveryCaseCreationResult,
    create_or_get_recovery_case,
)

OPENED_AT = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_concurrent_case_creation_is_idempotent_and_audited() -> None:
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

    webhook_id = uuid4()
    payment_attempt_id = uuid4()
    unique_suffix = uuid4().hex
    provider_event_id = f"evt_recovery_case_{unique_suffix}"
    provider_payment_id = f"pay_recovery_case_{unique_suffix}"

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_recovery_case_test",
        provider_created_at=OPENED_AT,
        payload={"event": "payment.failed"},
        payload_sha256="c" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=OPENED_AT,
        last_received_at=OPENED_AT,
        processed_at=OPENED_AT,
    )
    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_recovery_case_test",
        provider_order_id=f"order_{unique_suffix}",
        amount_minor=249_900,
        currency="INR",
        method="upi",
        payment_created_at=OPENED_AT - timedelta(minutes=1),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=OPENED_AT,
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment failed",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=True,
    )

    async def create_once() -> RecoveryCaseCreationResult:
        async with session_factory() as session, session.begin():
            return await create_or_get_recovery_case(
                session,
                payment_attempt_id=payment_attempt_id,
                opened_at=OPENED_AT,
                customer_contact_allowed=True,
            )

    recovery_case_id: UUID | None = None

    try:
        async with session_factory() as session, session.begin():
            session.add(webhook)
            await session.flush()
            session.add(payment_attempt)

        results = await asyncio.gather(
            create_once(),
            create_once(),
        )

        dispositions = [result.disposition for result in results]

        assert dispositions.count(RecoveryCaseCreationDisposition.CREATED) == 1
        assert dispositions.count(RecoveryCaseCreationDisposition.EXISTING) == 1

        case_ids = {
            result.recovery_case.id for result in results if result.recovery_case is not None
        }
        assert len(case_ids) == 1
        recovery_case_id = case_ids.pop()

        created_result = next(
            result
            for result in results
            if result.disposition is RecoveryCaseCreationDisposition.CREATED
        )
        existing_result = next(
            result
            for result in results
            if result.disposition is RecoveryCaseCreationDisposition.EXISTING
        )

        assert created_result.audit_event is not None
        assert created_result.audit_event.sequence_number == 1
        assert created_result.audit_event.event_type == "case.opened"
        assert existing_result.audit_event is None

        async with session_factory() as session:
            case_count_result = await session.execute(
                select(func.count(RecoveryCase.id)).where(
                    RecoveryCase.payment_attempt_id == payment_attempt_id,
                ),
            )
            audit_count_result = await session.execute(
                select(func.count(RecoveryAuditEvent.id)).where(
                    RecoveryAuditEvent.recovery_case_id == recovery_case_id,
                ),
            )
            audit_result = await session.execute(
                select(RecoveryAuditEvent).where(
                    RecoveryAuditEvent.recovery_case_id == recovery_case_id,
                ),
            )
            verification = await verify_persisted_recovery_audit_chain(
                session,
                recovery_case_id=recovery_case_id,
            )

            case_count = case_count_result.scalar_one()
            audit_count = audit_count_result.scalar_one()
            audit_event = audit_result.scalar_one()

        assert case_count == 1
        assert audit_count == 1
        assert audit_event.sequence_number == 1
        assert audit_event.previous_event_hash is None
        assert audit_event.event_data["payment_attempt_id"] == str(payment_attempt_id)
        assert audit_event.event_data["amount_minor"] == 249_900
        assert verification.valid is True
        assert verification.checked_event_count == 1
    finally:
        try:
            async with session_factory() as cleanup_session, cleanup_session.begin():
                if recovery_case_id is not None:
                    await cleanup_session.execute(
                        delete(RecoveryCase).where(
                            RecoveryCase.id == recovery_case_id,
                        ),
                    )
                await cleanup_session.execute(
                    delete(PaymentAttempt).where(
                        PaymentAttempt.id == payment_attempt_id,
                    ),
                )
                await cleanup_session.execute(
                    delete(WebhookEvent).where(WebhookEvent.id == webhook_id),
                )
        finally:
            await engine.dispose()
