from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAuditEvent,
    RecoveryCase,
)
from app.db.models.recovery_outcome import (
    RecoveryOutcome,
    RecoveryOutcomeObservation,
)
from app.db.models.webhook import (
    WebhookEvent,
    WebhookProcessingStatus,
)
from app.domain.recovery import (
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlanDecision,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkStatus,
)
from app.services.recovery_audit_store import (
    verify_persisted_recovery_audit_chain,
)
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    create_or_get_recovery_case,
)
from app.services.recovery_outcome_reconciler import (
    complete_recovery_outcome_reconciliation,
    prepare_recovery_outcome_reconciliation,
)
from app.services.recovery_plan_service import (
    plan_and_persist_recovery_case,
)

RECONCILED_AT = datetime(
    2026,
    8,
    25,
    18,
    0,
    tzinfo=UTC,
)


@pytest.mark.asyncio
async def test_paid_payment_link_reconciles_once_and_closes_case() -> None:
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

    provider_event_id = f"evt_outcome_reconciler_{unique_suffix}"
    provider_payment_id = f"pay_outcome_reconciler_{unique_suffix}"
    payment_link_id = f"plink_outcome_reconciler_{unique_suffix}"

    recovery_case_id: UUID | None = None
    recovery_action_id: UUID | None = None
    recovery_outcome_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_outcome_reconciler_test",
        provider_created_at=RECONCILED_AT - timedelta(minutes=5),
        payload={"event": "payment.failed"},
        payload_sha256="f" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=RECONCILED_AT - timedelta(minutes=5),
        last_received_at=RECONCILED_AT - timedelta(minutes=5),
        processed_at=RECONCILED_AT - timedelta(minutes=5),
    )
    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_outcome_reconciler_test",
        provider_order_id=f"order_{unique_suffix}",
        amount_minor=349_900,
        currency="INR",
        method="upi",
        payment_created_at=RECONCILED_AT - timedelta(minutes=6),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=RECONCILED_AT - timedelta(minutes=5),
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
                opened_at=RECONCILED_AT - timedelta(minutes=4),
                customer_contact_allowed=True,
            )

            assert creation.disposition is RecoveryCaseCreationDisposition.CREATED
            assert creation.recovery_case is not None

            recovery_case_id = creation.recovery_case.id

        async with session_factory() as session, session.begin():
            planned = await plan_and_persist_recovery_case(
                session,
                recovery_case_id=recovery_case_id,
                available_channels=(RecoveryChannel.EMAIL,),
                alternate_payment_methods=("card", "netbanking"),
                planned_at=RECONCILED_AT - timedelta(minutes=3),
            )

            assert planned.plan.decision is RecoveryPlanDecision.RECOVER

        async with session_factory() as session, session.begin():
            action_result = await session.execute(
                select(RecoveryAction)
                .where(
                    RecoveryAction.recovery_case_id == recovery_case_id,
                    RecoveryAction.action_type == "create_payment_link",
                )
                .with_for_update(),
            )
            payment_link_action = action_result.scalar_one()

            case_result = await session.execute(
                select(RecoveryCase)
                .where(
                    RecoveryCase.id == recovery_case_id,
                )
                .with_for_update(),
            )
            recovery_case = case_result.scalar_one()

            payment_link_action.status = RecoveryActionStatus.SUCCEEDED.value
            payment_link_action.provider_action_id = payment_link_id
            payment_link_action.provider_action_status = "created"
            payment_link_action.execution_attempt_count = 1
            payment_link_action.started_at = RECONCILED_AT - timedelta(minutes=2)
            payment_link_action.completed_at = RECONCILED_AT - timedelta(minutes=2)

            recovery_case.active_payment_link_id = payment_link_id
            recovery_case.version += 1

            recovery_action_id = payment_link_action.id

        assert recovery_case_id is not None
        assert recovery_action_id is not None

        payment_link = RazorpayPaymentLink.model_validate(
            {
                "id": payment_link_id,
                "short_url": "https://rzp.io/i/outcome-reconciler-test",
                "status": RazorpayPaymentLinkStatus.PAID.value,
                "amount": 349_900,
                "amount_paid": 349_900,
                "currency": "INR",
                "reference_id": f"rr_{recovery_action_id.hex}",
                "updated_at": int(RECONCILED_AT.timestamp()),
            },
        )

        async with session_factory() as session, session.begin():
            prepared = await prepare_recovery_outcome_reconciliation(
                session,
                recovery_case_id=recovery_case_id,
                recovery_action_id=recovery_action_id,
            )

        async with session_factory() as session, session.begin():
            first_result = await complete_recovery_outcome_reconciliation(
                session,
                prepared=prepared,
                payment_link=payment_link,
                reconciled_at=RECONCILED_AT,
            )

            recovery_outcome_id = first_result.recovery_outcome_id

            assert first_result.projection_created is True
            assert first_result.projection_updated is True
            assert first_result.observation_created is True
            assert first_result.case_marked_recovered is True

        async with session_factory() as session, session.begin():
            replay_prepared = await prepare_recovery_outcome_reconciliation(
                session,
                recovery_case_id=recovery_case_id,
                recovery_action_id=recovery_action_id,
            )
            replay_result = await complete_recovery_outcome_reconciliation(
                session,
                prepared=replay_prepared,
                payment_link=payment_link,
                reconciled_at=RECONCILED_AT,
            )

            assert replay_result.recovery_outcome_id == recovery_outcome_id
            assert replay_result.projection_created is False
            assert replay_result.projection_updated is False
            assert replay_result.observation_created is False
            assert replay_result.case_marked_recovered is False

        async with session_factory() as session:
            case_result = await session.execute(
                select(RecoveryCase).where(
                    RecoveryCase.id == recovery_case_id,
                ),
            )
            outcome_result = await session.execute(
                select(RecoveryOutcome).where(
                    RecoveryOutcome.id == recovery_outcome_id,
                ),
            )
            observation_result = await session.execute(
                select(RecoveryOutcomeObservation)
                .where(
                    RecoveryOutcomeObservation.recovery_outcome_id == recovery_outcome_id,
                )
                .order_by(
                    RecoveryOutcomeObservation.created_at,
                ),
            )
            audit_result = await session.execute(
                select(RecoveryAuditEvent)
                .where(
                    RecoveryAuditEvent.recovery_case_id == recovery_case_id,
                    RecoveryAuditEvent.event_type == "outcome.payment_link.reconciled",
                )
                .order_by(
                    RecoveryAuditEvent.sequence_number,
                ),
            )
            verification = await verify_persisted_recovery_audit_chain(
                session,
                recovery_case_id=recovery_case_id,
            )

            stored_case = case_result.scalar_one()
            stored_outcome = outcome_result.scalar_one()
            observations = tuple(observation_result.scalars().all())
            reconciliation_events = tuple(audit_result.scalars().all())

        assert stored_case.status == RecoveryCaseStatus.RECOVERED.value
        assert stored_case.recovered_at == RECONCILED_AT
        assert stored_case.closed_at == RECONCILED_AT
        assert stored_case.close_reason == "payment_link_recovered"
        assert stored_case.active_payment_link_id is None

        assert stored_outcome.status == "recovered"
        assert stored_outcome.attribution == "direct_payment_link"
        assert stored_outcome.gross_recovered_minor == 349_900
        assert stored_outcome.duplicate_collection_prevented_minor == 0
        assert stored_outcome.payment_link_id == payment_link_id

        assert len(observations) == 1
        assert len(reconciliation_events) == 1
        assert verification.valid is True
    finally:
        try:
            async with session_factory() as cleanup_session, cleanup_session.begin():
                if recovery_outcome_id is not None:
                    await cleanup_session.execute(
                        delete(RecoveryOutcome).where(
                            RecoveryOutcome.id == recovery_outcome_id,
                        ),
                    )

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
                    delete(WebhookEvent).where(
                        WebhookEvent.id == webhook_id,
                    ),
                )
        finally:
            await engine.dispose()
