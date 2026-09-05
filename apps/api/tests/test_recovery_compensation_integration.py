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
    execute_recovery_payment_link_action,
)
from app.services.recovery_audit_store import (
    verify_persisted_recovery_audit_chain,
)
from app.services.recovery_case_service import (
    create_or_get_recovery_case,
)
from app.services.recovery_compensation_service import (
    RecoveryCompensationDisposition,
    compensate_late_authorized_recovery,
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
LINK_EXECUTED_AT = PLANNED_AT + timedelta(minutes=1)
LATE_AUTHORIZED_AT = PLANNED_AT + timedelta(minutes=2)
COMPENSATED_AT = PLANNED_AT + timedelta(minutes=3)


@pytest.mark.asyncio
async def test_late_authorization_cancels_active_link_and_pending_actions() -> None:
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
    suffix = uuid4().hex

    provider_event_id = f"evt_compensation_{suffix}"
    provider_payment_id = f"pay_compensation_{suffix}"
    payment_link_id = f"plink_{suffix}"

    recovery_case_id: UUID | None = None
    action_id: UUID | None = None

    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type="payment.failed",
        account_id="acc_compensation_test",
        provider_created_at=(PLANNED_AT - timedelta(minutes=5)),
        payload={
            "event": "payment.failed",
        },
        payload_sha256="c" * 64,
        processing_status=(WebhookProcessingStatus.PROCESSED.value),
        delivery_count=1,
        first_received_at=(PLANNED_AT - timedelta(minutes=5)),
        last_received_at=(PLANNED_AT - timedelta(minutes=5)),
        processed_at=(PLANNED_AT - timedelta(minutes=5)),
    )

    payment_attempt = PaymentAttempt(
        id=payment_attempt_id,
        provider="razorpay",
        provider_payment_id=(provider_payment_id),
        account_id="acc_compensation_test",
        provider_order_id=f"order_{suffix}",
        amount_minor=100,
        currency="INR",
        method="upi",
        payment_created_at=(PLANNED_AT - timedelta(minutes=6)),
        current_state="failed",
        state_version=1,
        state_provider_event_id=(provider_event_id),
        state_webhook_event_id=webhook_id,
        state_event_created_at=(PLANNED_AT - timedelta(minutes=5)),
        error_code="BAD_REQUEST_ERROR",
        error_description=("Payment authentication failed"),
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=True,
    )

    provider_requests: list[tuple[str, str]] = []

    provider_link: dict[str, object] | None = None

    async def provider_handler(
        request: httpx2.Request,
    ) -> httpx2.Response:
        nonlocal provider_link

        provider_requests.append(
            (
                request.method,
                request.url.path,
            ),
        )

        if request.method == "GET":
            links = [] if provider_link is None else [provider_link]

            return httpx2.Response(
                200,
                request=request,
                json={
                    "payment_links": links,
                },
            )

        if request.url.path.endswith(
            "/cancel",
        ):
            assert provider_link is not None

            provider_link = {
                **provider_link,
                "status": "cancelled",
            }

            return httpx2.Response(
                200,
                request=request,
                json=provider_link,
            )

        assert request.method == "POST"

        payload = json.loads(
            request.content,
        )

        provider_link = {
            "id": payment_link_id,
            "short_url": ("https://rzp.io/i/compensation-test"),
            "status": "created",
            "amount": payload["amount"],
            "currency": payload["currency"],
            "reference_id": (payload["reference_id"]),
        }

        return httpx2.Response(
            200,
            request=request,
            json=provider_link,
        )

    provider = RazorpayPaymentLinkProvider(
        key_id="rzp_test_compensation",
        key_secret="compensation-secret",
        base_url=("https://api.razorpay.test"),
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

        await execute_recovery_payment_link_action(
            session_factory,
            action_id=action_id,
            provider=provider,
            executed_at=LINK_EXECUTED_AT,
        )

        async with session_factory.begin() as session:
            payment_result = await session.execute(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.id == payment_attempt_id,
                )
                .with_for_update(),
            )

            stored_payment = payment_result.scalar_one()

            stored_payment.current_state = "authorized"
            stored_payment.state_version = 2
            stored_payment.state_provider_event_id = f"evt_authorized_{suffix}"
            stored_payment.state_event_created_at = LATE_AUTHORIZED_AT
            stored_payment.recovery_eligible = False
            stored_payment.recovery_stopped_at = LATE_AUTHORIZED_AT
            stored_payment.recovery_stop_reason = "late_authorization"
            stored_payment.late_authorization_detected_at = LATE_AUTHORIZED_AT

        first_result = await compensate_late_authorized_recovery(
            session_factory,
            recovery_case_id=recovery_case_id,
            provider=provider,
            compensated_at=COMPENSATED_AT,
        )

        replay_result = await compensate_late_authorized_recovery(
            session_factory,
            recovery_case_id=recovery_case_id,
            provider=provider,
            compensated_at=(COMPENSATED_AT + timedelta(seconds=1)),
        )

        assert first_result.disposition is (RecoveryCompensationDisposition.CANCELLED)

        assert replay_result.disposition is (RecoveryCompensationDisposition.ALREADY_CANCELLED)

        assert provider_requests == [
            (
                "POST",
                "/v1/payment_links",
            ),
            (
                "GET",
                "/v1/payment_links",
            ),
            (
                "POST",
                (f"/v1/payment_links/{payment_link_id}/cancel"),
            ),
        ]

        async with session_factory() as session:
            case_result = await session.execute(
                select(RecoveryCase).where(
                    RecoveryCase.id == recovery_case_id,
                ),
            )

            actions_result = await session.execute(
                select(RecoveryAction)
                .where(
                    RecoveryAction.recovery_case_id == recovery_case_id,
                )
                .order_by(
                    RecoveryAction.sequence_number,
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

            stored_actions = tuple(
                actions_result.scalars().all(),
            )

            audit_events = tuple(
                audit_result.scalars().all(),
            )

        assert stored_case.status == (RecoveryCaseStatus.CANCELLED.value)
        assert stored_case.active_payment_link_id is None
        assert stored_case.closed_at == COMPENSATED_AT
        assert stored_case.close_reason == ("late_authorization_payment_link_cancelled")
        assert stored_case.late_authorization_detected_at == LATE_AUTHORIZED_AT

        stored_link_action = next(action for action in stored_actions if action.id == action_id)

        assert stored_link_action.status == (RecoveryActionStatus.SUCCEEDED.value)
        assert stored_link_action.provider_action_status == "cancelled"

        assert all(
            action.status == RecoveryActionStatus.CANCELLED.value
            for action in stored_actions
            if action.id != action_id
        )

        assert [event.event_type for event in audit_events][-2:] == [
            ("recovery.late_authorization.detected"),
            "action.payment_link.cancelled",
        ]

        assert verification.valid is True

    finally:
        if recovery_case_id is not None:
            async with session_factory.begin() as session:
                await session.execute(
                    delete(RecoveryCase).where(
                        RecoveryCase.id == recovery_case_id,
                    ),
                )

                await session.execute(
                    delete(PaymentAttempt).where(
                        PaymentAttempt.id == payment_attempt_id,
                    ),
                )

                await session.execute(
                    delete(WebhookEvent).where(
                        WebhookEvent.id == webhook_id,
                    ),
                )

        await engine.dispose()
