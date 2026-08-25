import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx2
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
from app.db.models.webhook import (
    WebhookEvent,
    WebhookProcessingStatus,
)
from app.domain.recovery import (
    RecoveryCaseStatus,
    RecoveryChannel,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
)
from app.services.recovery_action_executor import (
    RecoveryActionExecutionDisposition,
    execute_recovery_payment_link_action,
)
from app.services.recovery_audit_store import (
    verify_persisted_recovery_audit_chain,
)
from app.services.recovery_case_service import (
    create_or_get_recovery_case,
)
from app.services.recovery_plan_service import (
    plan_and_persist_recovery_case,
)

PLANNED_AT = datetime(
    2026,
    8,
    25,
    17,
    0,
    tzinfo=UTC,
)
EXECUTED_AT = PLANNED_AT + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_payment_link_action_is_executed_and_replayed_idempotently() -> None:
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

    provider_event_id = f"evt_action_executor_{unique_suffix}"
    provider_payment_id = f"pay_action_executor_{unique_suffix}"

    recovery_case_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_action_executor_test",
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
        account_id="acc_action_executor_test",
        provider_order_id=(f"order_{unique_suffix}"),
        amount_minor=199_900,
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

    provider_requests: list[str] = []

    async def provider_handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        provider_requests.append(
            request.method,
        )

        if request.method == "GET":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "payment_links": [],
                },
            )

        assert request.method == "POST"

        payload = json.loads(
            request.content,
        )

        return httpx2.Response(
            200,
            request=request,
            json={
                "id": f"plink_{unique_suffix}",
                "short_url": ("https://rzp.io/i/integration-test"),
                "status": "created",
                "amount": payload["amount"],
                "currency": payload["currency"],
                "reference_id": (payload["reference_id"]),
            },
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_integration",
        key_secret="integration-secret",
        base_url="https://api.razorpay.test",
        transport=httpx2.MockTransport(
            provider_handler,
        ),
    )

    try:
        async with session_factory.begin() as session:
            session.add(webhook)
            await session.flush()
            session.add(payment_attempt)

        async with session_factory.begin() as session:
            creation = await create_or_get_recovery_case(
                session,
                payment_attempt_id=(payment_attempt_id),
                opened_at=(PLANNED_AT - timedelta(minutes=4)),
                customer_contact_allowed=True,
            )

            assert creation.recovery_case is not None

            recovery_case_id = creation.recovery_case.id

        async with session_factory.begin() as session:
            persisted = await plan_and_persist_recovery_case(
                session,
                recovery_case_id=(recovery_case_id),
                available_channels=(RecoveryChannel.EMAIL,),
                alternate_payment_methods=("card",),
                planned_at=PLANNED_AT,
            )

            payment_link_action = next(
                action
                for action in persisted.actions
                if action.action_type == "create_payment_link"
            )

            action_id = payment_link_action.id

        first_result = await execute_recovery_payment_link_action(
            session_factory,
            action_id=action_id,
            provider=provider,
            executed_at=EXECUTED_AT,
        )

        replay_result = await execute_recovery_payment_link_action(
            session_factory,
            action_id=action_id,
            provider=provider,
            executed_at=(EXECUTED_AT + timedelta(seconds=1)),
        )

        assert first_result.disposition is RecoveryActionExecutionDisposition.SUCCEEDED
        assert first_result.payment_link is not None
        assert first_result.recovered_existing_link is False

        assert replay_result.disposition is RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED

        assert provider_requests == [
            "GET",
            "POST",
        ]

        async with session_factory() as session:
            case_result = await session.execute(
                select(RecoveryCase).where(
                    RecoveryCase.id == recovery_case_id,
                ),
            )

            action_result = await session.execute(
                select(RecoveryAction).where(
                    RecoveryAction.id == action_id,
                ),
            )

            audit_result = await session.execute(
                select(RecoveryAuditEvent)
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
            stored_action = action_result.scalar_one()
            audit_events = tuple(
                audit_result.scalars().all(),
            )

        assert stored_action.status == (RecoveryActionStatus.SUCCEEDED.value)
        assert stored_action.execution_attempt_count == 1
        assert stored_action.provider_action_id == (f"plink_{unique_suffix}")
        assert stored_action.provider_action_status == "created"
        assert stored_action.last_error is None
        assert stored_action.completed_at == EXECUTED_AT

        assert stored_case.status == (RecoveryCaseStatus.READY.value)
        assert stored_case.active_payment_link_id == f"plink_{unique_suffix}"
        assert stored_case.recovery_attempt_count == 1
        assert stored_case.version == 3

        assert [event.event_type for event in audit_events] == [
            "case.opened",
            "agent.plan.persisted",
            "action.payment_link.started",
            "action.payment_link.succeeded",
        ]

        assert audit_events[-1].recovery_action_id == action_id
        assert verification.valid is True
        assert verification.checked_event_count == 4
    finally:
        try:
            async with session_factory.begin() as cleanup_session:
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
