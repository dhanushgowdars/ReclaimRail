from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import (
    close_database,
    get_session_factory,
)
from app.db.models.incident import (
    IncidentDetectionObservation,
    RevenueIncident,
)
from app.db.models.payment import (
    PaymentAttempt,
    PaymentStateTransition,
)
from app.db.models.webhook import WebhookEvent
from app.domain.incidents import (
    IncidentDetectionOutcome,
    IncidentScope,
    IncidentSeverity,
    build_incident_fingerprint,
)
from app.services.incident_detection_runner import (
    run_payment_method_incident_detection,
)

REFERENCE_TIME = datetime(
    2031,
    1,
    1,
    10,
    2,
    tzinfo=UTC,
)

CURRENT_WINDOW_END = datetime(
    2031,
    1,
    1,
    10,
    0,
    tzinfo=UTC,
)

ATTEMPTS_PER_WINDOW = 20
BASELINE_WINDOW_COUNT = 6
AMOUNT_MINOR = 100_000


def create_webhook(
    *,
    webhook_id: UUID,
    provider_event_id: str,
    event_type: str,
    occurred_at: datetime,
) -> WebhookEvent:
    return WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type=event_type,
        provider_created_at=occurred_at,
        payload={"event": event_type},
        payload_sha256="1" * 64,
        processing_status="processed",
        processed_at=occurred_at,
    )


def create_attempt(
    *,
    attempt_id: UUID,
    webhook_id: UUID,
    provider_event_id: str,
    provider_payment_id: str,
    payment_method: str,
    state: str,
    occurred_at: datetime,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=attempt_id,
        provider="razorpay",
        provider_payment_id=provider_payment_id,
        amount_minor=AMOUNT_MINOR,
        currency="INR",
        method=payment_method,
        payment_created_at=occurred_at,
        current_state=state,
        state_version=1,
        state_provider_event_id=provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=occurred_at,
        recovery_eligible=state == "failed",
    )


def create_transition(
    *,
    attempt_id: UUID,
    webhook_id: UUID,
    provider_event_id: str,
    state: str,
    occurred_at: datetime,
) -> PaymentStateTransition:
    event_type = f"payment.{state}"

    return PaymentStateTransition(
        id=uuid4(),
        payment_attempt_id=attempt_id,
        webhook_event_id=webhook_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        previous_state="unknown",
        incoming_state=state,
        resulting_state=state,
        resulting_version=1,
        outcome="applied",
        reason="initialized",
        late_authorization=False,
        stop_recovery=False,
        event_created_at=occurred_at,
        processed_at=occurred_at,
    )


@pytest.mark.asyncio
async def test_runner_creates_incident_from_real_payment_history() -> None:
    unique_suffix = uuid4().hex[:12]
    payment_method = f"upi-runner-{unique_suffix}"

    fingerprint = build_incident_fingerprint(
        IncidentScope.PAYMENT_METHOD,
        payment_method,
    )

    webhooks: list[WebhookEvent] = []
    attempts: list[PaymentAttempt] = []
    transitions: list[PaymentStateTransition] = []

    webhook_ids: list[UUID] = []
    attempt_ids: list[UUID] = []

    series_start = CURRENT_WINDOW_END - timedelta(
        minutes=5 * (BASELINE_WINDOW_COUNT + 1),
    )

    for window_index in range(
        BASELINE_WINDOW_COUNT + 1,
    ):
        window_start = series_start + timedelta(
            minutes=5 * window_index,
        )

        failed_attempt_count = 8 if window_index == BASELINE_WINDOW_COUNT else 1

        for attempt_index in range(ATTEMPTS_PER_WINDOW):
            occurred_at = window_start + timedelta(
                seconds=attempt_index + 1,
            )

            failed = attempt_index < failed_attempt_count
            state = "failed" if failed else "captured"
            event_type = f"payment.{state}"

            webhook_id = uuid4()
            attempt_id = uuid4()

            provider_event_id = f"evt-{unique_suffix}-{window_index}-{attempt_index}"
            provider_payment_id = f"pay-{unique_suffix}-{window_index}-{attempt_index}"

            webhook_ids.append(webhook_id)
            attempt_ids.append(attempt_id)

            webhooks.append(
                create_webhook(
                    webhook_id=webhook_id,
                    provider_event_id=provider_event_id,
                    event_type=event_type,
                    occurred_at=occurred_at,
                ),
            )
            attempts.append(
                create_attempt(
                    attempt_id=attempt_id,
                    webhook_id=webhook_id,
                    provider_event_id=provider_event_id,
                    provider_payment_id=provider_payment_id,
                    payment_method=payment_method,
                    state=state,
                    occurred_at=occurred_at,
                ),
            )
            transitions.append(
                create_transition(
                    attempt_id=attempt_id,
                    webhook_id=webhook_id,
                    provider_event_id=provider_event_id,
                    state=state,
                    occurred_at=occurred_at,
                ),
            )

    session_factory = get_session_factory()
    detector_run_id = uuid4()

    try:
        async with session_factory() as session, session.begin():
            session.add_all(webhooks)
            await session.flush()

            session.add_all(attempts)
            await session.flush()

            session.add_all(transitions)

        async with session_factory() as session, session.begin():
            result = await run_payment_method_incident_detection(
                session,
                payment_method=payment_method,
                currency="INR",
                reference_time=REFERENCE_TIME,
                detector_run_id=detector_run_id,
                detected_at=REFERENCE_TIME,
                baseline_window_count=(BASELINE_WINDOW_COUNT),
            )

        assert result.current_window_end == CURRENT_WINDOW_END
        assert result.metrics.total_attempts == 20
        assert result.metrics.failed_attempts == 8
        assert result.metrics.total_amount_minor == 2_000_000
        assert result.metrics.failed_amount_minor == 800_000

        assert result.baseline.window_count == 6
        assert result.baseline.median_failure_rate == (pytest.approx(0.05))

        assert result.decision.outcome is (IncidentDetectionOutcome.INCIDENT)
        assert result.decision.severity is (IncidentSeverity.HIGH)
        assert result.decision.failure_rate == (pytest.approx(0.40))

        async with session_factory() as session:
            incident = (
                await session.execute(
                    select(RevenueIncident).where(
                        RevenueIncident.fingerprint == fingerprint,
                        RevenueIncident.currency == "INR",
                    ),
                )
            ).scalar_one()

            observation = (
                await session.execute(
                    select(
                        IncidentDetectionObservation,
                    ).where(
                        IncidentDetectionObservation.detector_run_id == detector_run_id,
                    ),
                )
            ).scalar_one()

        assert incident.status == "open"
        assert incident.severity == "high"
        assert incident.total_attempts == 20
        assert incident.failed_attempts == 8
        assert incident.revenue_at_risk_minor == 800_000
        assert incident.occurrence_count == 1

        assert observation.incident_id == incident.id
        assert observation.fingerprint == fingerprint
        assert observation.outcome == "incident"
        assert observation.severity == "high"
        assert observation.total_attempts == 20
        assert observation.failed_attempts == 8

    finally:
        try:
            async with (
                session_factory() as cleanup_session,
                cleanup_session.begin(),
            ):
                await cleanup_session.execute(
                    delete(
                        IncidentDetectionObservation,
                    ).where(
                        IncidentDetectionObservation.fingerprint == fingerprint,
                    ),
                )
                await cleanup_session.execute(
                    delete(RevenueIncident).where(
                        RevenueIncident.fingerprint == fingerprint,
                    ),
                )
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
