from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAgentRun,
    RecoveryAgentRunStatus,
    RecoveryAuditEvent,
    RecoveryCase,
    RecoveryPlannerProvider,
)
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.recovery import RecoveryCaseStatus, RecoveryChannel, RecoveryPlanDecision
from app.services.recovery_audit_store import verify_persisted_recovery_audit_chain
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    create_or_get_recovery_case,
)
from app.services.recovery_plan_service import plan_and_persist_recovery_case

PLANNED_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_recovery_plan_is_persisted_and_audited_atomically() -> None:
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
    provider_event_id = f"evt_recovery_plan_{unique_suffix}"
    provider_payment_id = f"pay_recovery_plan_{unique_suffix}"
    recovery_case_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_recovery_plan_test",
        provider_created_at=PLANNED_AT - timedelta(minutes=5),
        payload={"event": "payment.failed"},
        payload_sha256="d" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=PLANNED_AT - timedelta(minutes=5),
        last_received_at=PLANNED_AT - timedelta(minutes=5),
        processed_at=PLANNED_AT - timedelta(minutes=5),
    )
    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_recovery_plan_test",
        provider_order_id=f"order_{unique_suffix}",
        amount_minor=349_900,
        currency="INR",
        method="upi",
        payment_created_at=PLANNED_AT - timedelta(minutes=6),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=PLANNED_AT - timedelta(minutes=5),
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment authentication failed",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=True,
    )

    try:
        async with session_factory() as session, session.begin():
            session.add(webhook)
            await session.flush()
            session.add(payment_attempt)

        async with session_factory() as session, session.begin():
            creation = await create_or_get_recovery_case(
                session,
                payment_attempt_id=payment_attempt_id,
                opened_at=PLANNED_AT - timedelta(minutes=4),
                customer_contact_allowed=True,
            )

            assert creation.disposition is RecoveryCaseCreationDisposition.CREATED
            assert creation.recovery_case is not None
            recovery_case_id = creation.recovery_case.id

        async with session_factory() as session, session.begin():
            persisted = await plan_and_persist_recovery_case(
                session,
                recovery_case_id=recovery_case_id,
                available_channels=(RecoveryChannel.EMAIL,),
                alternate_payment_methods=("card", "netbanking"),
                planned_at=PLANNED_AT,
            )

            assert persisted.plan.decision is RecoveryPlanDecision.RECOVER
            assert len(persisted.actions) == 3

        async with session_factory() as session:
            case_result = await session.execute(
                select(RecoveryCase).where(RecoveryCase.id == recovery_case_id),
            )
            run_result = await session.execute(
                select(RecoveryAgentRun).where(
                    RecoveryAgentRun.recovery_case_id == recovery_case_id,
                ),
            )
            action_result = await session.execute(
                select(RecoveryAction)
                .where(RecoveryAction.recovery_case_id == recovery_case_id)
                .order_by(RecoveryAction.sequence_number),
            )
            audit_result = await session.execute(
                select(RecoveryAuditEvent)
                .where(RecoveryAuditEvent.recovery_case_id == recovery_case_id)
                .order_by(RecoveryAuditEvent.sequence_number),
            )
            verification = await verify_persisted_recovery_audit_chain(
                session,
                recovery_case_id=recovery_case_id,
            )

            stored_case = case_result.scalar_one()
            stored_run = run_result.scalar_one()
            stored_actions = tuple(action_result.scalars().all())
            stored_audit_events = tuple(audit_result.scalars().all())

        assert stored_case.status == RecoveryCaseStatus.READY.value
        assert stored_case.version == 1
        assert stored_case.next_action_at == PLANNED_AT

        assert stored_run.run_number == 1
        assert stored_run.status == RecoveryAgentRunStatus.SUCCEEDED.value
        assert stored_run.planner_provider == RecoveryPlannerProvider.DETERMINISTIC.value
        assert stored_run.proposed_action_count == 3
        assert stored_run.reasoning_summary

        assert [action.sequence_number for action in stored_actions] == [1, 2, 3]
        assert [action.action_type for action in stored_actions] == [
            "create_payment_link",
            "offer_alternate_method",
            "send_recovery_message",
        ]
        assert {action.status for action in stored_actions} == {
            RecoveryActionStatus.ALLOWED.value,
        }
        assert {action.policy_outcome for action in stored_actions} == {"allow"}
        assert len({action.idempotency_key for action in stored_actions}) == 3

        assert [event.sequence_number for event in stored_audit_events] == [1, 2]
        assert [event.event_type for event in stored_audit_events] == [
            "case.opened",
            "agent.plan.persisted",
        ]
        assert stored_audit_events[1].agent_run_id == stored_run.id
        assert stored_audit_events[1].previous_event_hash == stored_audit_events[0].event_hash
        assert verification.valid is True
        assert verification.checked_event_count == 2
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
