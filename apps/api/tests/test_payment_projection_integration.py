from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import get_session_factory
from app.db.models.payment import (
    PaymentAttempt,
    PaymentStateTransition,
)
from app.db.models.webhook import (
    WebhookEvent,
    WebhookProcessingStatus,
)
from app.domain.payments import (
    PaymentState,
    PaymentTransitionOutcome,
    PaymentTransitionReason,
)
from app.services.payment_webhook_processor import (
    PaymentWebhookDisposition,
    process_canonical_payment_webhook,
)

PAYMENT_CREATED_TIMESTAMP = 1_787_550_000
FAILED_EVENT_TIMESTAMP = 1_787_550_120
AUTHORIZED_EVENT_TIMESTAMP = 1_787_550_240

PAYMENT_CREATED_AT = datetime.fromtimestamp(
    PAYMENT_CREATED_TIMESTAMP,
    tz=UTC,
)
FAILED_EVENT_AT = datetime.fromtimestamp(
    FAILED_EVENT_TIMESTAMP,
    tz=UTC,
)
AUTHORIZED_EVENT_AT = datetime.fromtimestamp(
    AUTHORIZED_EVENT_TIMESTAMP,
    tz=UTC,
)

FAILED_PROCESSED_AT = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
AUTHORIZED_PROCESSED_AT = datetime(2026, 8, 24, 9, 1, tzinfo=UTC)


def payment_payload(
    *,
    event_type: str,
    status: str,
    payment_id: str,
    event_timestamp: int,
) -> dict[str, object]:
    is_failure = status == PaymentState.FAILED.value

    return {
        "entity": "event",
        "account_id": "acc_integration_test",
        "event": event_type,
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 50_000,
                    "currency": "INR",
                    "status": status,
                    "order_id": f"order_{payment_id}",
                    "method": "upi",
                    "created_at": PAYMENT_CREATED_TIMESTAMP,
                    "error_code": ("BAD_REQUEST_ERROR" if is_failure else None),
                    "error_description": ("Payment declined" if is_failure else None),
                    "error_source": ("customer" if is_failure else None),
                    "error_step": ("payment_authentication" if is_failure else None),
                    "error_reason": ("payment_failed" if is_failure else None),
                },
            },
        },
        "created_at": event_timestamp,
    }


def make_webhook_event(
    *,
    webhook_id: UUID,
    provider_event_id: str,
    event_type: str,
    status: str,
    payment_id: str,
    event_timestamp: int,
) -> WebhookEvent:
    event_time = datetime.fromtimestamp(
        event_timestamp,
        tz=UTC,
    )

    return WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type=event_type,
        account_id="acc_integration_test",
        provider_created_at=event_time,
        payload=payment_payload(
            event_type=event_type,
            status=status,
            payment_id=payment_id,
            event_timestamp=event_timestamp,
        ),
        payload_sha256="b" * 64,
        processing_status=WebhookProcessingStatus.RECEIVED.value,
        delivery_count=1,
        first_received_at=event_time,
        last_received_at=event_time,
        processed_at=None,
    )


@pytest.mark.asyncio
async def test_failure_then_late_authorization_is_atomic_and_idempotent() -> None:
    session_factory = get_session_factory()

    payment_id = f"pay_integration_{uuid4().hex}"
    failed_webhook_id = uuid4()
    authorized_webhook_id = uuid4()

    failed_provider_event_id = f"evt_failed_{uuid4().hex}"
    authorized_provider_event_id = f"evt_authorized_{uuid4().hex}"

    failed_webhook = make_webhook_event(
        webhook_id=failed_webhook_id,
        provider_event_id=failed_provider_event_id,
        event_type="payment.failed",
        status=PaymentState.FAILED.value,
        payment_id=payment_id,
        event_timestamp=FAILED_EVENT_TIMESTAMP,
    )
    authorized_webhook = make_webhook_event(
        webhook_id=authorized_webhook_id,
        provider_event_id=authorized_provider_event_id,
        event_type="payment.authorized",
        status=PaymentState.AUTHORIZED.value,
        payment_id=payment_id,
        event_timestamp=AUTHORIZED_EVENT_TIMESTAMP,
    )

    try:
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    failed_webhook,
                    authorized_webhook,
                ],
            )

        async with session_factory() as session, session.begin():
            failed_result = await process_canonical_payment_webhook(
                session,
                failed_webhook_id,
                processed_at=FAILED_PROCESSED_AT,
            )

        assert failed_result.disposition is (PaymentWebhookDisposition.PROJECTED)
        assert failed_result.projection is not None
        assert failed_result.projection.state is PaymentState.FAILED

        async with session_factory() as session, session.begin():
            authorized_result = await process_canonical_payment_webhook(
                session,
                authorized_webhook_id,
                processed_at=AUTHORIZED_PROCESSED_AT,
            )

        assert authorized_result.disposition is (PaymentWebhookDisposition.PROJECTED)
        assert authorized_result.projection is not None
        assert authorized_result.projection.state is (PaymentState.AUTHORIZED)
        assert authorized_result.projection.reason is (PaymentTransitionReason.LATE_AUTHORIZATION)

        async with session_factory() as session, session.begin():
            replay_result = await process_canonical_payment_webhook(
                session,
                authorized_webhook_id,
                processed_at=AUTHORIZED_PROCESSED_AT,
            )

        assert replay_result.disposition is (PaymentWebhookDisposition.DUPLICATE)

        async with session_factory() as session:
            attempt_result = await session.execute(
                select(PaymentAttempt).where(
                    PaymentAttempt.provider == "razorpay",
                    PaymentAttempt.provider_payment_id == payment_id,
                ),
            )
            attempt = attempt_result.scalar_one()

            transition_result = await session.execute(
                select(PaymentStateTransition)
                .where(
                    PaymentStateTransition.payment_attempt_id == attempt.id,
                )
                .order_by(
                    PaymentStateTransition.event_created_at,
                ),
            )
            transitions = list(
                transition_result.scalars().all(),
            )

            failed_event = await session.get(
                WebhookEvent,
                failed_webhook_id,
            )
            authorized_event = await session.get(
                WebhookEvent,
                authorized_webhook_id,
            )

            assert attempt.current_state == (PaymentState.AUTHORIZED.value)
            assert attempt.state_version == 2
            assert attempt.recovery_eligible is False
            assert attempt.recovery_stopped_at == (AUTHORIZED_PROCESSED_AT)
            assert attempt.recovery_stop_reason == ("late_authorization")
            assert attempt.late_authorization_detected_at == (AUTHORIZED_EVENT_AT)
            assert attempt.error_code is None
            assert attempt.error_description is None

            assert len(transitions) == 2

            assert transitions[0].incoming_state == (PaymentState.FAILED.value)
            assert transitions[0].outcome == (PaymentTransitionOutcome.APPLIED.value)
            assert transitions[0].reason == (PaymentTransitionReason.INITIALIZED.value)

            assert transitions[1].incoming_state == (PaymentState.AUTHORIZED.value)
            assert transitions[1].outcome == (PaymentTransitionOutcome.APPLIED.value)
            assert transitions[1].reason == (PaymentTransitionReason.LATE_AUTHORIZATION.value)
            assert transitions[1].late_authorization is True
            assert transitions[1].stop_recovery is True

            assert failed_event is not None
            assert failed_event.processing_status == (WebhookProcessingStatus.PROCESSED.value)

            assert authorized_event is not None
            assert authorized_event.processing_status == (WebhookProcessingStatus.PROCESSED.value)

    finally:
        async with session_factory() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                delete(PaymentStateTransition).where(
                    PaymentStateTransition.webhook_event_id.in_(
                        [
                            failed_webhook_id,
                            authorized_webhook_id,
                        ],
                    ),
                ),
            )
            await cleanup_session.execute(
                delete(PaymentAttempt).where(
                    PaymentAttempt.provider == "razorpay",
                    PaymentAttempt.provider_payment_id == payment_id,
                ),
            )
            await cleanup_session.execute(
                delete(WebhookEvent).where(
                    WebhookEvent.id.in_(
                        [
                            failed_webhook_id,
                            authorized_webhook_id,
                        ],
                    ),
                ),
            )
