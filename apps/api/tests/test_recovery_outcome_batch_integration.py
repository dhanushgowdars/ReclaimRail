from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
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
    RecoveryCase,
)
from app.db.models.recovery_outcome import RecoveryOutcome
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
from app.services import recovery_outcome_batch
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    create_or_get_recovery_case,
)
from app.services.recovery_outcome_batch import (
    discover_reconcilable_recovery_action_ids,
    run_recovery_outcome_batch,
)
from app.services.recovery_plan_service import (
    plan_and_persist_recovery_case,
)

REFERENCE_TIME = datetime(
    2026,
    8,
    25,
    19,
    0,
    tzinfo=UTC,
)


@pytest.mark.asyncio
async def test_batch_reconciles_paid_link_once_and_skips_terminal_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    provider_event_id = f"evt_outcome_batch_{unique_suffix}"
    provider_payment_id = f"pay_outcome_batch_{unique_suffix}"
    payment_link_id = f"plink_outcome_batch_{unique_suffix}"

    recovery_case_id: UUID | None = None
    recovery_action_id: UUID | None = None
    recovery_outcome_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_outcome_batch_test",
        provider_created_at=REFERENCE_TIME - timedelta(minutes=5),
        payload={"event": "payment.failed"},
        payload_sha256="a" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=REFERENCE_TIME - timedelta(minutes=5),
        last_received_at=REFERENCE_TIME - timedelta(minutes=5),
        processed_at=REFERENCE_TIME - timedelta(minutes=5),
    )
    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_outcome_batch_test",
        provider_order_id=f"order_{unique_suffix}",
        amount_minor=349_900,
        currency="INR",
        method="upi",
        payment_created_at=REFERENCE_TIME - timedelta(minutes=6),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=REFERENCE_TIME - timedelta(minutes=5),
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
                opened_at=REFERENCE_TIME - timedelta(minutes=4),
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
                planned_at=REFERENCE_TIME - timedelta(minutes=3),
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
            payment_link_action.started_at = REFERENCE_TIME - timedelta(minutes=2)
            payment_link_action.completed_at = REFERENCE_TIME - timedelta(minutes=2)

            recovery_case.active_payment_link_id = payment_link_id
            recovery_case.version += 1

            recovery_action_id = payment_link_action.id

        assert recovery_case_id is not None
        assert recovery_action_id is not None

        payment_link = RazorpayPaymentLink.model_validate(
            {
                "id": payment_link_id,
                "short_url": "https://rzp.io/i/outcome-batch-test",
                "status": RazorpayPaymentLinkStatus.PAID.value,
                "amount": 349_900,
                "amount_paid": 349_900,
                "currency": "INR",
                "reference_id": f"rr_{recovery_action_id.hex}",
                "updated_at": int(REFERENCE_TIME.timestamp()),
            },
        )

        provider = MagicMock()
        provider.fetch_payment_link = AsyncMock(
            return_value=payment_link,
        )

        # The local development database also contains your manual Razorpay
        # demo records. This isolates this integration test's own action
        # without touching or deleting your real demo data.
        monkeypatch.setattr(
            recovery_outcome_batch,
            "discover_reconcilable_recovery_action_ids",
            AsyncMock(
                return_value=(recovery_action_id,),
            ),
        )

        first_batch = await run_recovery_outcome_batch(
            session_factory,
            provider=provider,
            reference_time=REFERENCE_TIME,
            batch_size=25,
        )

        assert first_batch.discovered == 1
        assert first_batch.reconciled == 1
        assert first_batch.recovered == 1
        assert first_batch.duplicate_collection_prevented == 0
        assert first_batch.retryable_failures == 0
        assert first_batch.permanent_failures == 0
        assert first_batch.skipped == 0

        provider.fetch_payment_link.assert_awaited_once_with(
            payment_link_id,
        )

        recovery_outcome_id = first_batch.reconciliation_results[0].recovery_outcome_id

        # Use the real discovery query here. It may see your manual demo
        # records, but this test's recovered action must not be selected again.
        async with session_factory() as session:
            remaining_action_ids = await discover_reconcilable_recovery_action_ids(
                session,
                reference_time=REFERENCE_TIME + timedelta(minutes=1),
                batch_size=100,
            )

        assert recovery_action_id not in remaining_action_ids

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

            stored_case = case_result.scalar_one()
            stored_outcome = outcome_result.scalar_one()

        assert stored_case.status == RecoveryCaseStatus.RECOVERED.value
        assert stored_outcome.status == "recovered"
        assert stored_outcome.gross_recovered_minor == 349_900
    finally:
        try:
            async with session_factory() as cleanup_session, cleanup_session.begin():
                if recovery_case_id is not None:
                    await cleanup_session.execute(
                        delete(RecoveryOutcome).where(
                            RecoveryOutcome.recovery_case_id == recovery_case_id,
                        ),
                    )
                    await cleanup_session.flush()

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
