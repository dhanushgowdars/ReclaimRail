import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.payment import PaymentAttempt
from app.db.models.payment_truth import (
    PaymentEvidenceRecord,
    PaymentTruthReconciliationState,
    PaymentTruthSnapshotRecord,
)
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.integrations.razorpay.orders import (
    RazorpayOrderPayment,
    RazorpayOrderPaymentStatus,
    RazorpayOrderProviderError,
    RazorpayProviderFailureKind,
)
from app.services.payment_truth_reconciliation import reconcile_payment_truth_batch

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


@dataclass
class UnavailableProvider:
    call_count: int = 0
    delay_seconds: float = 0

    async def fetch_order_payments(self, _order_id: str) -> tuple[RazorpayOrderPayment, ...]:
        self.call_count += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        raise RazorpayOrderProviderError(
            "provider unavailable",
            retryable=True,
            kind=RazorpayProviderFailureKind.READ_TIMEOUT,
        )


@dataclass
class RecoveringProvider:
    payment: RazorpayOrderPayment
    call_count: int = 0

    async def fetch_order_payments(self, _order_id: str) -> tuple[RazorpayOrderPayment, ...]:
        self.call_count += 1
        if self.call_count == 1:
            raise RazorpayOrderProviderError(
                "provider unavailable",
                retryable=True,
                kind=RazorpayProviderFailureKind.READ_TIMEOUT,
            )
        return (self.payment,)


async def _insert_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    evidence_source: str,
) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    webhook_id = uuid4()
    attempt_id = uuid4()
    event = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=f"evt_reconciliation_{suffix}",
        event_type="payment.failed",
        provider_created_at=NOW - timedelta(minutes=1),
        payload={
            "event": "payment.failed",
            "reclaimrail_evidence_source": evidence_source,
        },
        payload_sha256="a" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=NOW - timedelta(minutes=1),
        last_received_at=NOW - timedelta(minutes=1),
        processed_at=NOW - timedelta(minutes=1),
    )
    attempt = PaymentAttempt(
        id=attempt_id,
        provider="razorpay",
        provider_payment_id=f"pay_reconciliation_{suffix}",
        provider_order_id=f"order_reconciliation_{suffix}",
        amount_minor=349_900,
        currency="INR",
        method="netbanking",
        payment_created_at=NOW - timedelta(minutes=2),
        current_state="failed",
        state_version=1,
        state_provider_event_id=event.provider_event_id,
        state_webhook_event_id=webhook_id,
        state_event_created_at=NOW - timedelta(minutes=1),
        recovery_eligible=True,
    )
    async with session_factory.begin() as session:
        session.add(event)
        await session.flush()
        session.add(attempt)
    return attempt_id, webhook_id


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    attempt_id: UUID,
    webhook_id: UUID,
) -> None:
    async with session_factory.begin() as session:
        attempt = await session.get(PaymentAttempt, attempt_id)
        provider_payment_id = attempt.provider_payment_id if attempt is not None else None
        await session.execute(delete(PaymentAttempt).where(PaymentAttempt.id == attempt_id))
        await session.execute(delete(WebhookEvent).where(WebhookEvent.id == webhook_id))
        if provider_payment_id is not None:
            await session.execute(
                delete(WebhookEvent).where(
                    WebhookEvent.provider_event_id.like(
                        f"provider-api:{provider_payment_id}:%",
                    ),
                ),
            )


def _database_url() -> str:
    settings = get_settings()
    if settings.database_url is None or not settings.database_url.get_secret_value():
        pytest.skip("Database URL is not configured")
    return settings.database_url.get_secret_value()


@pytest.mark.asyncio
async def test_unavailable_provider_is_not_called_again_inside_persisted_cooldown() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    attempt_id, webhook_id = await _insert_attempt(
        session_factory,
        evidence_source="verified_webhook",
    )
    provider = UnavailableProvider()

    try:
        first = await reconcile_payment_truth_batch(
            session_factory,
            provider=provider,  # type: ignore[arg-type]
            reference_time=NOW,
            batch_size=1,
            retry_base_delay=timedelta(seconds=60),
            payment_attempt_ids=(attempt_id,),
        )
        second = await reconcile_payment_truth_batch(
            session_factory,
            provider=provider,  # type: ignore[arg-type]
            reference_time=NOW + timedelta(seconds=1),
            batch_size=1,
            retry_base_delay=timedelta(seconds=60),
            payment_attempt_ids=(attempt_id,),
        )

        async with session_factory() as session:
            evidence_count = int(
                await session.scalar(
                    select(func.count(PaymentEvidenceRecord.id)).where(
                        PaymentEvidenceRecord.payment_attempt_id == attempt_id,
                    ),
                )
            )
            truth_count = int(
                await session.scalar(
                    select(func.count(PaymentTruthSnapshotRecord.id)).where(
                        PaymentTruthSnapshotRecord.payment_attempt_id == attempt_id,
                    ),
                )
            )
            control = await session.get(PaymentTruthReconciliationState, attempt_id)

        assert first.provider_calls == 1
        assert first.unavailable == 1
        assert second.provider_calls == 0
        assert second.checked == 0
        assert provider.call_count == 1
        assert evidence_count == 1
        assert truth_count == 1
        assert control is not None
        assert control.attempt_count == 1
        assert control.next_retry_at == NOW + timedelta(seconds=60)
    finally:
        await _cleanup(session_factory, attempt_id=attempt_id, webhook_id=webhook_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_batches_share_one_persisted_provider_budget() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    attempt_id, webhook_id = await _insert_attempt(
        session_factory,
        evidence_source="verified_webhook",
    )
    provider = UnavailableProvider(delay_seconds=0.05)

    async def run_batch() -> None:
        await reconcile_payment_truth_batch(
            session_factory,
            provider=provider,  # type: ignore[arg-type]
            reference_time=NOW,
            batch_size=1,
            retry_base_delay=timedelta(seconds=60),
            payment_attempt_ids=(attempt_id,),
        )

    try:
        await asyncio.gather(run_batch(), run_batch())

        async with session_factory() as session:
            evidence_count = int(
                await session.scalar(
                    select(func.count(PaymentEvidenceRecord.id)).where(
                        PaymentEvidenceRecord.payment_attempt_id == attempt_id,
                    ),
                )
            )
            truth_count = int(
                await session.scalar(
                    select(func.count(PaymentTruthSnapshotRecord.id)).where(
                        PaymentTruthSnapshotRecord.payment_attempt_id == attempt_id,
                    ),
                )
            )

        assert provider.call_count == 1
        assert evidence_count == 1
        assert truth_count == 1
    finally:
        await _cleanup(session_factory, attempt_id=attempt_id, webhook_id=webhook_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_controlled_synthetic_evidence_never_calls_provider_adapter() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    attempt_id, webhook_id = await _insert_attempt(
        session_factory,
        evidence_source="controlled_synthetic",
    )
    provider = UnavailableProvider()

    try:
        result = await reconcile_payment_truth_batch(
            session_factory,
            provider=provider,  # type: ignore[arg-type]
            reference_time=NOW,
            batch_size=1,
            payment_attempt_ids=(attempt_id,),
        )
        async with session_factory() as session:
            control = await session.get(PaymentTruthReconciliationState, attempt_id)

        assert result.synthetic_blocked == 1
        assert result.provider_calls == 0
        assert provider.call_count == 0
        assert control is not None
        assert control.blocked_reason == "controlled_synthetic"
        assert control.exhausted_at == NOW
    finally:
        await _cleanup(session_factory, attempt_id=attempt_id, webhook_id=webhook_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_provider_evidence_recovers_after_unavailable_evidence_expires() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    attempt_id, webhook_id = await _insert_attempt(
        session_factory,
        evidence_source="verified_webhook",
    )
    async with session_factory() as session:
        attempt = await session.get(PaymentAttempt, attempt_id)
        assert attempt is not None
        provider = RecoveringProvider(
            payment=RazorpayOrderPayment(
                id=attempt.provider_payment_id,
                amount=attempt.amount_minor,
                currency=attempt.currency,
                status=RazorpayOrderPaymentStatus.FAILED,
                order_id=attempt.provider_order_id,
                method=attempt.method,
                created_at=int(NOW.timestamp()),
                error_code="BAD_REQUEST_ERROR",
                error_reason="payment_failed",
            ),
        )

    try:
        unavailable = await reconcile_payment_truth_batch(
            session_factory,
            provider=provider,  # type: ignore[arg-type]
            reference_time=NOW,
            batch_size=1,
            retry_base_delay=timedelta(seconds=15),
            payment_attempt_ids=(attempt_id,),
        )
        recovered = await reconcile_payment_truth_batch(
            session_factory,
            provider=provider,  # type: ignore[arg-type]
            reference_time=NOW + timedelta(seconds=121),
            batch_size=1,
            retry_base_delay=timedelta(seconds=15),
            payment_attempt_ids=(attempt_id,),
        )

        async with session_factory() as session:
            attempt = await session.get(PaymentAttempt, attempt_id)
            control = await session.get(PaymentTruthReconciliationState, attempt_id)
            latest_truth = await session.scalar(
                select(PaymentTruthSnapshotRecord)
                .where(PaymentTruthSnapshotRecord.payment_attempt_id == attempt_id)
                .order_by(PaymentTruthSnapshotRecord.version.desc())
                .limit(1),
            )

        assert unavailable.unavailable == 1
        assert recovered.projected == 1
        assert provider.call_count == 2
        assert attempt is not None
        assert attempt.recovery_eligible is True
        assert control is not None
        assert control.attempt_count == 0
        assert control.next_retry_at == NOW + timedelta(seconds=241)
        assert latest_truth is not None
        assert latest_truth.state == "payment_failed"
    finally:
        await _cleanup(session_factory, attempt_id=attempt_id, webhook_id=webhook_id)
        await engine.dispose()
