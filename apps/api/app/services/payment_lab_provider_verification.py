"""Provider API fallback for Payment Lab evidence when a webhook is delayed.

The fallback is deliberately server-side and records its source in the durable
provider event payload. It never accepts a browser callback as payment truth.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.integrations.razorpay.orders import (
    RazorpayOrderPayment,
    RazorpayOrderPaymentStatus,
    RazorpayOrderProvider,
    RazorpayOrderProviderError,
)
from app.services.payment_webhook_processor import process_canonical_payment_webhook

SessionFactory = async_sessionmaker[AsyncSession]
PROVIDER_API_EVIDENCE_SOURCE = "razorpay_api_verification"
VERIFY_AFTER = timedelta(seconds=3)
VERIFIABLE_RUN_STATUSES = (
    PaymentLabRunStatus.CHECKOUT_READY.value,
    PaymentLabRunStatus.PAYMENT_ATTEMPTED.value,
    PaymentLabRunStatus.RECOVERY_RUNNING.value,
)


@dataclass(frozen=True, slots=True)
class ProviderVerificationResult:
    checked: int
    projected: int
    no_payment_yet: int
    failures: int


def _event_type(status: RazorpayOrderPaymentStatus) -> str:
    return f"payment.{status.value}"


def _payload(payment: RazorpayOrderPayment) -> tuple[dict[str, object], bytes]:
    payload: dict[str, object] = {
        "entity": "event",
        "event": _event_type(payment.status),
        "contains": ["payment"],
        "payload": {"payment": {"entity": payment.model_dump(by_alias=True)}},
        "created_at": payment.provider_created_at,
        "reclaimrail_evidence_source": PROVIDER_API_EVIDENCE_SOURCE,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return payload, raw


async def _candidate_ids(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
) -> tuple[UUID, ...]:
    result = await session.execute(
        select(PaymentLabRun.id)
        .where(
            PaymentLabRun.status.in_(VERIFIABLE_RUN_STATUSES),
            PaymentLabRun.provider_order_id.is_not(None),
            # Before an attempt exists, an expired checkout cannot gain new
            # payment evidence. Once the provider API supplied an attempt,
            # keep observing it so a delayed authorisation can safely re-plan.
            or_(
                PaymentLabRun.payment_attempt_id.is_not(None),
                PaymentLabRun.checkout_expires_at > reference_time,
            ),
            or_(
                PaymentLabRun.payment_attempt_id.is_(None),
                PaymentLabRun.provider_evidence_source == PROVIDER_API_EVIDENCE_SOURCE,
            ),
            or_(
                PaymentLabRun.provider_evidence_checked_at.is_(None),
                PaymentLabRun.provider_evidence_checked_at <= reference_time - VERIFY_AFTER,
            ),
        )
        .order_by(PaymentLabRun.created_at)
        .limit(batch_size),
    )
    return tuple(result.scalars())


async def _verify_one(
    session: AsyncSession,
    *,
    payment_lab_run_id: UUID,
    provider: RazorpayOrderProvider,
    reference_time: datetime,
) -> str:
    result = await session.execute(
        select(PaymentLabRun).where(PaymentLabRun.id == payment_lab_run_id).with_for_update(),
    )
    run = result.scalar_one_or_none()
    if (
        run is None
        or run.status not in VERIFIABLE_RUN_STATUSES
        or run.provider_order_id is None
        or (
            run.payment_attempt_id is not None
            and run.provider_evidence_source != PROVIDER_API_EVIDENCE_SOURCE
        )
    ):
        return "skipped"

    payments = await provider.fetch_order_payments(run.provider_order_id)
    run.provider_evidence_checked_at = reference_time

    matching = tuple(
        payment
        for payment in payments
        if payment.order_id == run.provider_order_id
        and payment.amount_minor == run.amount_minor
        and payment.currency == run.currency
    )
    if not matching:
        await session.commit()
        return "no_payment"

    payment = max(matching, key=lambda item: item.provider_created_at)
    provider_event_id = f"provider-api:{payment.payment_id}:{payment.status.value}"
    existing_event = await session.scalar(
        select(WebhookEvent.id).where(
            WebhookEvent.provider == "razorpay",
            WebhookEvent.provider_event_id == provider_event_id,
        ),
    )
    if existing_event is not None:
        await session.commit()
        return "already_current"

    payload, raw = _payload(payment)
    event = WebhookEvent(
        id=uuid4(),
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type=_event_type(payment.status),
        account_id=None,
        provider_created_at=datetime.fromtimestamp(payment.provider_created_at, tz=UTC),
        payload=payload,
        payload_sha256=hashlib.sha256(raw).hexdigest(),
        processing_status=WebhookProcessingStatus.RECEIVED.value,
        delivery_count=1,
        first_received_at=reference_time,
        last_received_at=reference_time,
    )
    session.add(event)
    await session.flush()
    await process_canonical_payment_webhook(
        session,
        event.id,
        processed_at=reference_time,
    )
    await session.commit()
    return "projected"


async def verify_payment_lab_provider_evidence_batch(
    session_factory: SessionFactory,
    *,
    provider: RazorpayOrderProvider,
    reference_time: datetime,
    batch_size: int,
) -> ProviderVerificationResult:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Provider verification time must be timezone-aware")
    if not 1 <= batch_size <= 100:
        raise ValueError("Provider verification batch size must be between 1 and 100")

    async with session_factory() as session:
        candidate_ids = await _candidate_ids(
            session,
            reference_time=reference_time,
            batch_size=batch_size,
        )

    projected = no_payment_yet = failures = 0
    for run_id in candidate_ids:
        try:
            async with session_factory() as session:
                outcome = await _verify_one(
                    session,
                    payment_lab_run_id=run_id,
                    provider=provider,
                    reference_time=reference_time,
                )
        except RazorpayOrderProviderError:
            failures += 1
            continue
        except Exception:
            failures += 1
            continue
        if outcome == "projected":
            projected += 1
        elif outcome == "no_payment":
            no_payment_yet += 1

    return ProviderVerificationResult(
        checked=len(candidate_ids),
        projected=projected,
        no_payment_yet=no_payment_yet,
        failures=failures,
    )
