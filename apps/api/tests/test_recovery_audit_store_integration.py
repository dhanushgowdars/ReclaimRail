from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAuditActor,
    RecoveryAuditEvent,
    RecoveryCase,
)
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.recovery import RecoveryCaseStatus
from app.services.recovery_audit import RecoveryAuditVerificationReason
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
    load_recovery_audit_chain,
    verify_persisted_recovery_audit_chain,
)

OCCURRED_AT = datetime(2026, 8, 25, 7, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_persisted_chain_detects_tampered_evidence() -> None:
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
    recovery_case_id = uuid4()
    unique_suffix = uuid4().hex
    provider_event_id = f"evt_recovery_audit_{unique_suffix}"
    provider_payment_id = f"pay_recovery_audit_{unique_suffix}"

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_recovery_audit_test",
        provider_created_at=OCCURRED_AT,
        payload={"event": "payment.failed"},
        payload_sha256="a" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=OCCURRED_AT,
        last_received_at=OCCURRED_AT,
        processed_at=OCCURRED_AT,
    )
    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_recovery_audit_test",
        provider_order_id=f"order_{unique_suffix}",
        amount_minor=149_900,
        currency="INR",
        method="upi",
        payment_created_at=OCCURRED_AT - timedelta(minutes=1),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=OCCURRED_AT,
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment failed",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=True,
    )
    recovery_case = RecoveryCase(
        id=recovery_case_id,
        payment_attempt_id=payment_attempt_id,
        status=RecoveryCaseStatus.OPEN.value,
        amount_minor=149_900,
        currency="INR",
        payment_method="upi",
        recovery_attempt_count=0,
        version=0,
        customer_contact_allowed=True,
        opened_at=OCCURRED_AT,
    )

    try:
        async with session_factory() as session, session.begin():
            session.add(webhook)
            await session.flush()
            session.add(payment_attempt)
            await session.flush()
            session.add(recovery_case)

        async with session_factory() as session, session.begin():
            first = await append_recovery_audit_event(
                session,
                recovery_case_id=recovery_case_id,
                request=RecoveryAuditAppendRequest(
                    event_type="case.opened",
                    actor_type=RecoveryAuditActor.SYSTEM,
                    event_data={
                        "amount_minor": 149_900,
                        "currency": "INR",
                    },
                    occurred_at=OCCURRED_AT,
                ),
            )

        async with session_factory() as session, session.begin():
            second = await append_recovery_audit_event(
                session,
                recovery_case_id=recovery_case_id,
                request=RecoveryAuditAppendRequest(
                    event_type="policy.action.allowed",
                    actor_type=RecoveryAuditActor.POLICY,
                    event_data={
                        "action_type": "create_payment_link",
                        "outcome": "allow",
                        "guardrails": [],
                    },
                    occurred_at=OCCURRED_AT + timedelta(seconds=1),
                ),
            )

        assert first.sequence_number == 1
        assert first.previous_event_hash is None
        assert second.sequence_number == 2
        assert second.previous_event_hash == first.event_hash

        async with session_factory() as session:
            entries = await load_recovery_audit_chain(
                session,
                recovery_case_id=recovery_case_id,
            )
            verification = await verify_persisted_recovery_audit_chain(
                session,
                recovery_case_id=recovery_case_id,
            )

        assert [entry.sequence_number for entry in entries] == [1, 2]
        assert verification.valid is True
        assert verification.reason is RecoveryAuditVerificationReason.VALID
        assert verification.checked_event_count == 2

        async with session_factory() as session, session.begin():
            tampered_result = await session.execute(
                select(RecoveryAuditEvent)
                .where(
                    RecoveryAuditEvent.recovery_case_id == recovery_case_id,
                    RecoveryAuditEvent.sequence_number == 2,
                )
                .with_for_update(),
            )
            tampered_event = tampered_result.scalar_one()
            tampered_event.event_data = {
                "action_type": "create_payment_link",
                "outcome": "allow",
                "guardrails": ["policy_bypassed"],
            }

        async with session_factory() as session:
            tampered_verification = await verify_persisted_recovery_audit_chain(
                session,
                recovery_case_id=recovery_case_id,
            )

        assert tampered_verification.valid is False
        assert tampered_verification.reason is (RecoveryAuditVerificationReason.EVENT_HASH_MISMATCH)
        assert tampered_verification.checked_event_count == 1
        assert tampered_verification.broken_sequence_number == 2
    finally:
        try:
            async with session_factory() as cleanup_session, cleanup_session.begin():
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
                    delete(WebhookEvent).where(
                        WebhookEvent.id == webhook_id,
                    ),
                )
        finally:
            await engine.dispose()
