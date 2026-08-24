from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from app.core.database import (
    close_database,
    get_session_factory,
)
from app.db.models.payment import (
    PaymentAttempt,
    PaymentStateTransition,
)
from app.db.models.webhook import WebhookEvent
from app.services.incident_window_aggregator import (
    load_payment_method_window_series,
)

WINDOW_END = datetime(
    2030,
    1,
    1,
    10,
    0,
    tzinfo=UTC,
)


def create_webhook(
    webhook_id: UUID,
    *,
    provider_event_id: str,
    event_type: str,
    occurred_at: datetime,
) -> WebhookEvent:
    return WebhookEvent(
        id=webhook_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        provider_created_at=occurred_at,
        payload={
            "event": event_type,
        },
        payload_sha256="0" * 64,
        processing_status="processed",
        processed_at=occurred_at,
    )


def create_attempt(
    attempt_id: UUID,
    *,
    payment_id: str,
    method: str,
    amount_minor: int,
    state: str,
    state_webhook_id: UUID,
    state_provider_event_id: str,
    state_event_created_at: datetime,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=attempt_id,
        provider="razorpay",
        provider_payment_id=payment_id,
        amount_minor=amount_minor,
        currency="INR",
        method=method,
        payment_created_at=state_event_created_at,
        current_state=state,
        state_version=1,
        state_provider_event_id=state_provider_event_id,
        state_webhook_event_id=state_webhook_id,
        state_event_created_at=state_event_created_at,
        recovery_eligible=state == "failed",
    )


def create_transition(
    *,
    attempt_id: UUID,
    webhook_id: UUID,
    provider_event_id: str,
    event_type: str,
    previous_state: str,
    incoming_state: str,
    resulting_state: str,
    resulting_version: int,
    occurred_at: datetime,
    reason: str,
    late_authorization: bool = False,
    stop_recovery: bool = False,
) -> PaymentStateTransition:
    return PaymentStateTransition(
        id=uuid4(),
        payment_attempt_id=attempt_id,
        webhook_event_id=webhook_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        previous_state=previous_state,
        incoming_state=incoming_state,
        resulting_state=resulting_state,
        resulting_version=resulting_version,
        outcome="applied",
        reason=reason,
        late_authorization=late_authorization,
        stop_recovery=stop_recovery,
        event_created_at=occurred_at,
        processed_at=occurred_at,
    )


@pytest.mark.asyncio
async def test_aggregates_first_outcome_without_late_authorization_rewrite() -> None:
    unique_suffix = uuid4().hex[:12]
    payment_method = f"upi-{unique_suffix}"

    baseline_attempt_id = uuid4()
    late_attempt_id = uuid4()
    captured_attempt_id = uuid4()

    baseline_webhook_id = uuid4()
    failed_webhook_id = uuid4()
    authorized_webhook_id = uuid4()
    captured_webhook_id = uuid4()

    baseline_event_id = f"evt-baseline-{unique_suffix}"
    failed_event_id = f"evt-failed-{unique_suffix}"
    authorized_event_id = f"evt-authorized-{unique_suffix}"
    captured_event_id = f"evt-captured-{unique_suffix}"

    baseline_time = WINDOW_END - timedelta(minutes=9)
    failed_time = WINDOW_END - timedelta(minutes=2)
    authorized_time = WINDOW_END - timedelta(minutes=1)
    captured_time = WINDOW_END - timedelta(minutes=3)

    webhook_ids = [
        baseline_webhook_id,
        failed_webhook_id,
        authorized_webhook_id,
        captured_webhook_id,
    ]
    attempt_ids = [
        baseline_attempt_id,
        late_attempt_id,
        captured_attempt_id,
    ]

    webhooks = [
        create_webhook(
            baseline_webhook_id,
            provider_event_id=baseline_event_id,
            event_type="payment.failed",
            occurred_at=baseline_time,
        ),
        create_webhook(
            failed_webhook_id,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            occurred_at=failed_time,
        ),
        create_webhook(
            authorized_webhook_id,
            provider_event_id=authorized_event_id,
            event_type="payment.authorized",
            occurred_at=authorized_time,
        ),
        create_webhook(
            captured_webhook_id,
            provider_event_id=captured_event_id,
            event_type="payment.captured",
            occurred_at=captured_time,
        ),
    ]

    attempts = [
        create_attempt(
            baseline_attempt_id,
            payment_id=f"pay-baseline-{unique_suffix}",
            method=payment_method,
            amount_minor=15_000,
            state="failed",
            state_webhook_id=baseline_webhook_id,
            state_provider_event_id=baseline_event_id,
            state_event_created_at=baseline_time,
        ),
        create_attempt(
            late_attempt_id,
            payment_id=f"pay-late-{unique_suffix}",
            method=payment_method,
            amount_minor=10_000,
            state="authorized",
            state_webhook_id=authorized_webhook_id,
            state_provider_event_id=authorized_event_id,
            state_event_created_at=authorized_time,
        ),
        create_attempt(
            captured_attempt_id,
            payment_id=f"pay-captured-{unique_suffix}",
            method=payment_method,
            amount_minor=20_000,
            state="captured",
            state_webhook_id=captured_webhook_id,
            state_provider_event_id=captured_event_id,
            state_event_created_at=captured_time,
        ),
    ]

    transitions = [
        create_transition(
            attempt_id=baseline_attempt_id,
            webhook_id=baseline_webhook_id,
            provider_event_id=baseline_event_id,
            event_type="payment.failed",
            previous_state="unknown",
            incoming_state="failed",
            resulting_state="failed",
            resulting_version=1,
            occurred_at=baseline_time,
            reason="initialized",
        ),
        create_transition(
            attempt_id=late_attempt_id,
            webhook_id=failed_webhook_id,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            previous_state="unknown",
            incoming_state="failed",
            resulting_state="failed",
            resulting_version=1,
            occurred_at=failed_time,
            reason="initialized",
        ),
        create_transition(
            attempt_id=late_attempt_id,
            webhook_id=authorized_webhook_id,
            provider_event_id=authorized_event_id,
            event_type="payment.authorized",
            previous_state="failed",
            incoming_state="authorized",
            resulting_state="authorized",
            resulting_version=2,
            occurred_at=authorized_time,
            reason="late_authorization",
            late_authorization=True,
            stop_recovery=True,
        ),
        create_transition(
            attempt_id=captured_attempt_id,
            webhook_id=captured_webhook_id,
            provider_event_id=captured_event_id,
            event_type="payment.captured",
            previous_state="unknown",
            incoming_state="captured",
            resulting_state="captured",
            resulting_version=1,
            occurred_at=captured_time,
            reason="initialized",
        ),
    ]

    session_factory = get_session_factory()

    try:
        async with session_factory() as session, session.begin():
            session.add_all(webhooks)
            await session.flush()

            session.add_all(attempts)
            await session.flush()

            session.add_all(transitions)

        async with session_factory() as session:
            series = await load_payment_method_window_series(
                session,
                payment_method=payment_method,
                currency="INR",
                current_window_end=WINDOW_END,
                baseline_window_count=2,
            )

        assert len(series.baseline_windows) == 2

        assert series.baseline_windows[0].total_attempts == 0

        second_baseline = series.baseline_windows[1]
        assert second_baseline.total_attempts == 1
        assert second_baseline.failed_attempts == 1
        assert second_baseline.failed_amount_minor == 15_000

        current = series.current_window
        assert current.total_attempts == 2
        assert current.failed_attempts == 1
        assert current.total_amount_minor == 30_000
        assert current.failed_amount_minor == 10_000
        assert current.failure_rate == pytest.approx(0.5)

    finally:
        try:
            async with (
                session_factory() as cleanup_session,
                cleanup_session.begin(),
            ):
                await cleanup_session.execute(
                    delete(PaymentStateTransition).where(
                        PaymentStateTransition.payment_attempt_id.in_(
                            attempt_ids,
                        ),
                    ),
                )
                await cleanup_session.execute(
                    delete(PaymentAttempt).where(
                        PaymentAttempt.id.in_(attempt_ids),
                    ),
                )
                await cleanup_session.execute(
                    delete(WebhookEvent).where(
                        WebhookEvent.id.in_(webhook_ids),
                    ),
                )
        finally:
            await close_database()
