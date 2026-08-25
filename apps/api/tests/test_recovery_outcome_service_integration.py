from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
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
    RecoveryChannel,
    RecoveryPlanDecision,
)
from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeProof,
    RecoveryOutcomeStatus,
)
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    create_or_get_recovery_case,
)
from app.services.recovery_outcome_service import (
    persist_recovery_outcome_proof,
)
from app.services.recovery_plan_service import (
    plan_and_persist_recovery_case,
)

RECONCILED_AT = datetime(2026, 8, 25, 15, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_recovered_outcome_is_persisted_once_with_immutable_evidence() -> None:
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
    provider_event_id = f"evt_outcome_failed_{unique_suffix}"
    provider_payment_id = f"pay_outcome_{unique_suffix}"
    recovery_case_id: UUID | None = None
    recovery_outcome_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_recovery_outcome_test",
        provider_created_at=RECONCILED_AT - timedelta(minutes=5),
        payload={"event": "payment.failed"},
        payload_sha256="e" * 64,
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
        account_id="acc_recovery_outcome_test",
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

        async with session_factory() as session:
            action_result = await session.execute(
                select(RecoveryAction)
                .where(
                    RecoveryAction.recovery_case_id == recovery_case_id,
                    RecoveryAction.action_type == "create_payment_link",
                )
                .order_by(RecoveryAction.sequence_number),
            )
            payment_link_action = action_result.scalar_one()

        proof = RecoveryOutcomeProof(
            recovery_case_id=recovery_case_id,
            payment_attempt_id=payment_attempt_id,
            recovery_action_id=payment_link_action.id,
            provider_payment_id=provider_payment_id,
            payment_link_id=f"plink_outcome_{unique_suffix}",
            provider_outcome_id=f"pay_outcome_{unique_suffix}",
            status=RecoveryOutcomeStatus.RECOVERED,
            attribution=RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
            original_amount_minor=349_900,
            currency="INR",
            occurred_at=RECONCILED_AT,
            gross_recovered_minor=349_900,
            reversed_minor=0,
            duplicate_collection_prevented_minor=0,
            evidence_event_ids=(
                f"evt_payment_link_paid_{unique_suffix}",
                f"evt_payment_captured_{unique_suffix}",
            ),
        )

        async with session_factory() as session, session.begin():
            first_result = await persist_recovery_outcome_proof(
                session,
                proof=proof,
            )

            recovery_outcome_id = first_result.recovery_outcome_id

            assert first_result.projection_created is True
            assert first_result.projection_updated is True
            assert first_result.observation_created is True

        async with session_factory() as session, session.begin():
            replay_result = await persist_recovery_outcome_proof(
                session,
                proof=proof,
            )

            assert replay_result.recovery_outcome_id == recovery_outcome_id
            assert replay_result.projection_created is False
            assert replay_result.projection_updated is False
            assert replay_result.observation_created is False

        async with session_factory() as session:
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
                .order_by(RecoveryOutcomeObservation.occurred_at),
            )

            stored_outcome = outcome_result.scalar_one()
            stored_observations = tuple(
                observation_result.scalars().all(),
            )

        assert stored_outcome.recovery_case_id == recovery_case_id
        assert stored_outcome.payment_attempt_id == payment_attempt_id
        assert stored_outcome.recovery_action_id == payment_link_action.id
        assert stored_outcome.status == RecoveryOutcomeStatus.RECOVERED.value
        assert stored_outcome.attribution == RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK.value
        assert stored_outcome.original_amount_minor == 349_900
        assert stored_outcome.gross_recovered_minor == 349_900
        assert stored_outcome.reversed_minor == 0
        assert stored_outcome.duplicate_collection_prevented_minor == 0
        assert stored_outcome.version == 0

        assert len(stored_observations) == 1
        assert stored_observations[0].recovery_outcome_id == stored_outcome.id
        assert stored_observations[0].status == RecoveryOutcomeStatus.RECOVERED.value
        assert stored_observations[0].gross_recovered_minor == 349_900
        assert len(stored_observations[0].observation_fingerprint) == 64
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
