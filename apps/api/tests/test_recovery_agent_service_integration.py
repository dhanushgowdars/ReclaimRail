from dataclasses import dataclass
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
    RecoveryAgentRun,
    RecoveryAuditEvent,
    RecoveryCase,
)
from app.db.models.webhook import (
    WebhookEvent,
    WebhookProcessingStatus,
)
from app.domain.recovery import (
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlanningContext,
)
from app.integrations.gemini import (
    GeminiProviderResponse,
    RecoveryPlannerSource,
)
from app.services.recovery_agent_service import (
    execute_recovery_agent,
)
from app.services.recovery_audit_store import (
    verify_persisted_recovery_audit_chain,
)
from app.services.recovery_case_service import (
    create_or_get_recovery_case,
)

PLANNED_AT = datetime(
    2026,
    8,
    25,
    15,
    0,
    tzinfo=UTC,
)


@dataclass
class StubGeminiProvider:
    model_name: str = "gemini-integration-test"
    call_count: int = 0

    async def generate_plan(
        self,
        context: RecoveryPlanningContext,
    ) -> GeminiProviderResponse:
        self.call_count += 1

        assert context.case.payment_state.value == "failed"
        assert context.case.amount_minor == 129_900

        return GeminiProviderResponse(
            structured_plan={
                "analysis": {
                    "root_cause_category": "customer_authentication_failure",
                    "recoverability_assessment": "Verified failure is eligible for recovery",
                    "confidence": 0.92,
                    "allowed_action_recommendation": "create_payment_link",
                    "evidence_references": [
                        "payment_state_snapshot",
                        "merchant_recovery_policy",
                    ],
                    "operator_explanation": (
                        "The failed payment can receive one exact-amount recovery link."
                    ),
                    "observations": [
                        {
                            "evidence_reference": "payment_state_snapshot",
                        },
                        {
                            "evidence_reference": "merchant_recovery_policy",
                        },
                    ],
                    "reasoning_items": [
                        {
                            "evidence_references": [
                                "payment_state_snapshot",
                                "merchant_recovery_policy",
                            ],
                            "interpretation": (
                                "The payment remains failed and policy permits "
                                "one bounded recovery action."
                            ),
                            "action_impact": (
                                "Recommend one exact-amount recovery payment link."
                            ),
                        },
                    ],
                    "alternatives_considered": [],
                    "known_uncertainties": [],
                },
                "decision": "recover",
                "reasoning_summary": ("Create one bounded retry link for the original payment"),
                "proposals": [
                    {
                        "action_type": "create_payment_link",
                        "reason": ("Offer one safe retry for the unchanged amount"),
                        "amount_minor": 129_900,
                        "currency": "INR",
                    },
                ],
            },
            model_name=self.model_name,
            input_token_count=240,
            output_token_count=61,
        )


@pytest.mark.asyncio
async def test_agent_persists_gemini_plan_through_real_policy_transaction() -> None:
    settings = get_settings()

    if settings.database_url is None:
        pytest.skip(
            "Database URL is not configured",
        )

    database_url = settings.database_url.get_secret_value()

    if not database_url:
        pytest.skip(
            "Database URL is empty",
        )

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

    provider_event_id = f"evt_recovery_agent_{unique_suffix}"
    provider_payment_id = f"pay_recovery_agent_{unique_suffix}"

    recovery_case_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_recovery_agent_test",
        provider_created_at=(PLANNED_AT - timedelta(minutes=5)),
        payload={
            "event": "payment.failed",
        },
        payload_sha256="e" * 64,
        processing_status=(WebhookProcessingStatus.PROCESSED.value),
        delivery_count=1,
        first_received_at=(PLANNED_AT - timedelta(minutes=5)),
        last_received_at=(PLANNED_AT - timedelta(minutes=5)),
        processed_at=(PLANNED_AT - timedelta(minutes=5)),
    )

    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        account_id="acc_recovery_agent_test",
        provider_order_id=(f"order_{unique_suffix}"),
        amount_minor=129_900,
        currency="INR",
        method="upi",
        payment_created_at=(PLANNED_AT - timedelta(minutes=6)),
        current_state="failed",
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=(PLANNED_AT - timedelta(minutes=5)),
        error_code="BAD_REQUEST_ERROR",
        error_description=("Payment authentication failed"),
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=True,
    )

    provider = StubGeminiProvider()

    try:
        async with (
            session_factory() as session,
            session.begin(),
        ):
            session.add(
                webhook,
            )
            await session.flush()

            session.add(
                payment_attempt,
            )

        async with (
            session_factory() as session,
            session.begin(),
        ):
            creation = await create_or_get_recovery_case(
                session,
                payment_attempt_id=payment_attempt_id,
                opened_at=(PLANNED_AT - timedelta(minutes=4)),
                customer_contact_allowed=True,
            )

            assert creation.recovery_case is not None

            recovery_case_id = creation.recovery_case.id

        execution = await execute_recovery_agent(
            session_factory,
            recovery_case_id=recovery_case_id,
            available_channels=(RecoveryChannel.EMAIL,),
            alternate_payment_methods=("card",),
            planned_at=PLANNED_AT,
            provider=provider,
        )

        assert provider.call_count == 1

        assert execution.planner_result.source is RecoveryPlannerSource.GEMINI
        assert execution.planner_result.fallback_used is False
        assert (
            len(
                execution.persisted_plan.actions,
            )
            == 1
        )

        async with session_factory() as session:
            case_result = await session.execute(
                select(
                    RecoveryCase,
                ).where(
                    RecoveryCase.id == recovery_case_id,
                ),
            )

            run_result = await session.execute(
                select(
                    RecoveryAgentRun,
                ).where(
                    RecoveryAgentRun.recovery_case_id == recovery_case_id,
                ),
            )

            action_result = await session.execute(
                select(
                    RecoveryAction,
                ).where(
                    RecoveryAction.recovery_case_id == recovery_case_id,
                ),
            )

            audit_result = await session.execute(
                select(
                    RecoveryAuditEvent,
                )
                .where(
                    RecoveryAuditEvent.recovery_case_id == recovery_case_id,
                )
                .order_by(
                    RecoveryAuditEvent.sequence_number,
                ),
            )

            verification = await verify_persisted_recovery_audit_chain(
                session,
                recovery_case_id=(recovery_case_id),
            )

            stored_case = case_result.scalar_one()
            stored_run = run_result.scalar_one()
            stored_action = action_result.scalar_one()
            stored_audit_events = tuple(
                audit_result.scalars().all(),
            )

        assert stored_case.status == RecoveryCaseStatus.READY.value

        assert stored_run.planner_provider == "gemini"
        assert stored_run.model_name == "gemini-integration-test"
        assert stored_run.prompt_version == "gemini-structured-v3"
        assert stored_run.input_token_count == 240
        assert stored_run.output_token_count == 61
        assert stored_run.evidence["planner"]["fallback_used"] is False

        assert stored_action.action_type == "create_payment_link"
        assert stored_action.status == RecoveryActionStatus.ALLOWED.value
        assert stored_action.policy_outcome == "allow"
        assert stored_action.amount_minor == 129_900
        assert stored_action.currency == "INR"

        assert [event.event_type for event in stored_audit_events] == [
            "case.opened",
            "agent.plan.persisted",
        ]

        assert stored_audit_events[1].event_data["planner_provider"] == "gemini"
        assert stored_audit_events[1].event_data["input_token_count"] == 240

        assert verification.valid is True
        assert verification.checked_event_count == 2

    finally:
        try:
            async with (
                session_factory() as cleanup_session,
                cleanup_session.begin(),
            ):
                if recovery_case_id is not None:
                    await cleanup_session.execute(
                        delete(
                            RecoveryCase,
                        ).where(
                            RecoveryCase.id == recovery_case_id,
                        ),
                    )

                await cleanup_session.execute(
                    delete(
                        PaymentAttempt,
                    ).where(
                        PaymentAttempt.id == payment_attempt_id,
                    ),
                )

                await cleanup_session.execute(
                    delete(
                        WebhookEvent,
                    ).where(
                        WebhookEvent.id == webhook_id,
                    ),
                )
        finally:
            await engine.dispose()
