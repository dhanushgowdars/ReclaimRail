from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.payment_lab import (
    PaymentLabRun,
    PaymentLabRunMode,
    PaymentLabRunProvenance,
    PaymentLabRunStatus,
)
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryAgentRun,
    RecoveryCase,
)
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.recovery import (
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlanningContext,
)
from app.integrations.gemini import GeminiProviderResponse, RecoveryPlannerSource
from app.services.payment_lab_recovery_service import (
    PaymentLabRecoveryStartDisposition,
    start_payment_lab_recovery,
)

STARTED_AT = datetime(2026, 8, 26, 17, 30, tzinfo=UTC)


@dataclass
class StubGeminiProvider:
    model_name: str = "gemini-payment-lab-integration"
    call_count: int = 0

    async def generate_plan(
        self,
        context: RecoveryPlanningContext,
    ) -> GeminiProviderResponse:
        self.call_count += 1

        return GeminiProviderResponse(
            structured_plan={
                "analysis": {
                    "root_cause_category": "test_mode_payment_failure",
                    "recoverability_assessment": "Verified failure is eligible for recovery",
                    "confidence": 0.92,
                    "allowed_action_recommendation": "create_payment_link",
                    "evidence_references": [
                        "payment_state_snapshot",
                        "merchant_recovery_policy",
                    ],
                    "operator_explanation": (
                        "The test payment failed and policy permits one exact-amount link."
                    ),
                },
                "decision": "recover",
                "reasoning_summary": ("Offer one bounded retry for the verified Test Mode failure"),
                "proposals": [
                    {
                        "action_type": "create_payment_link",
                        "reason": "Preserve the original amount and currency",
                        "amount_minor": context.case.amount_minor,
                        "currency": context.case.currency,
                    },
                ],
            },
            model_name=self.model_name,
            input_token_count=210,
            output_token_count=54,
        )


@pytest.mark.asyncio
async def test_verified_lab_failure_starts_agent_once() -> None:
    settings = get_settings()

    if settings.database_url is None:
        pytest.skip("Database URL is not configured")

    database_url = settings.database_url.get_secret_value()

    if not database_url:
        pytest.skip("Database URL is empty")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    unique_suffix = uuid4().hex
    webhook_id = uuid4()
    payment_attempt_id = uuid4()
    payment_lab_run_id = uuid4()
    provider_event_id = f"evt_lab_agent_{unique_suffix}"
    provider_payment_id = f"pay_lab_agent_{unique_suffix}"
    provider_order_id = f"order_lab_agent_{unique_suffix}"
    recovery_case_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_payment_lab_agent_test",
        provider_created_at=STARTED_AT - timedelta(minutes=1),
        payload={"event": "payment.failed"},
        payload_sha256="a" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=STARTED_AT - timedelta(minutes=1),
        last_received_at=STARTED_AT - timedelta(minutes=1),
        processed_at=STARTED_AT - timedelta(minutes=1),
    )
    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_payment_lab_agent_test",
        provider_order_id=provider_order_id,
        amount_minor=349_900,
        currency="INR",
        method="netbanking",
        payment_created_at=STARTED_AT - timedelta(minutes=2),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=STARTED_AT - timedelta(minutes=1),
        error_code="BAD_REQUEST_ERROR",
        error_description="Test bank declined the payment",
        error_source="bank",
        error_step="payment_authorization",
        error_reason="payment_failed",
        recovery_eligible=True,
    )
    payment_lab_run = PaymentLabRun(
        id=payment_lab_run_id,
        client_request_id=uuid4(),
        mode=PaymentLabRunMode.GUIDED.value,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        status=PaymentLabRunStatus.PAYMENT_ATTEMPTED.value,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        receipt=f"rr_lab_{payment_lab_run_id.hex}",
        provider_order_id=provider_order_id,
        provider_order_status="created",
        provider_created_at=STARTED_AT - timedelta(minutes=2),
        payment_attempt_id=payment_attempt_id,
        failure_code="BAD_REQUEST_ERROR",
        checkout_expires_at=STARTED_AT + timedelta(minutes=8),
        created_at=STARTED_AT - timedelta(minutes=2),
        updated_at=STARTED_AT - timedelta(minutes=1),
        version=2,
    )
    provider = StubGeminiProvider()

    try:
        async with session_factory.begin() as session:
            session.add(webhook)
            await session.flush()
            session.add(payment_attempt)
            await session.flush()
            session.add(payment_lab_run)

        first = await start_payment_lab_recovery(
            session_factory,
            payment_lab_run_id=payment_lab_run_id,
            started_at=STARTED_AT,
            customer_contact_allowed=True,
            available_channels=(RecoveryChannel.EMAIL,),
            alternate_payment_methods=("card", "upi"),
            provider=provider,
        )
        recovery_case_id = first.recovery_case_id

        replay = await start_payment_lab_recovery(
            session_factory,
            payment_lab_run_id=payment_lab_run_id,
            started_at=STARTED_AT + timedelta(seconds=1),
            customer_contact_allowed=True,
            available_channels=(RecoveryChannel.EMAIL,),
            alternate_payment_methods=("card", "upi"),
            provider=provider,
        )

        async with session_factory() as session:
            stored_run = await session.get(PaymentLabRun, payment_lab_run_id)
            stored_case = await session.get(RecoveryCase, recovery_case_id)
            agent_run_count = int(
                (
                    await session.execute(
                        select(func.count(RecoveryAgentRun.id)).where(
                            RecoveryAgentRun.recovery_case_id == recovery_case_id,
                        ),
                    )
                ).scalar_one(),
            )
            action_count = int(
                (
                    await session.execute(
                        select(func.count(RecoveryAction.id)).where(
                            RecoveryAction.recovery_case_id == recovery_case_id,
                        ),
                    )
                ).scalar_one(),
            )

        assert first.disposition is PaymentLabRecoveryStartDisposition.STARTED
        assert first.recovery_case_created is True
        assert first.planner_source is RecoveryPlannerSource.GEMINI
        assert first.planner_fallback_used is False

        assert replay.disposition is (PaymentLabRecoveryStartDisposition.ALREADY_RUNNING)
        assert provider.call_count == 1

        assert stored_run is not None
        assert stored_run.status == PaymentLabRunStatus.RECOVERY_RUNNING.value
        assert stored_run.version == 3
        assert stored_case is not None
        assert stored_case.status == RecoveryCaseStatus.READY.value
        assert stored_case.customer_contact_allowed is True
        assert agent_run_count == 1
        assert action_count == 1
    finally:
        try:
            async with session_factory.begin() as cleanup_session:
                await cleanup_session.execute(
                    delete(PaymentLabRun).where(PaymentLabRun.id == payment_lab_run_id),
                )
                if recovery_case_id is not None:
                    await cleanup_session.execute(
                        delete(RecoveryCase).where(
                            RecoveryCase.id == recovery_case_id,
                        ),
                    )
                await cleanup_session.execute(
                    delete(PaymentAttempt).where(PaymentAttempt.id == payment_attempt_id),
                )
                await cleanup_session.execute(
                    delete(WebhookEvent).where(WebhookEvent.id == webhook_id),
                )
        finally:
            await engine.dispose()
