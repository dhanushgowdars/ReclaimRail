import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_truth import PaymentTruthSnapshotRecord
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.recovery.contracts import PaymentEvidenceSource, PaymentTruthState
from app.integrations.razorpay.orders import (
    RazorpayOrderPayment,
    RazorpayOrderProvider,
    RazorpayOrderProviderError,
)
from app.services.payment_truth_service import (
    PaymentEvidenceWrite,
    canonical_sha256,
    record_payment_evidence,
    resolve_and_persist_payment_truth,
)
from app.services.payment_webhook_processor import process_canonical_payment_webhook

SessionFactory = async_sessionmaker[AsyncSession]
RECONCILE_AFTER = timedelta(minutes=2)
CIRCUIT_FAILURE_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class PaymentTruthReconciliationResult:
    checked: int
    projected: int
    unchanged: int
    unavailable: int
    persistence_failures: int
    circuit_opened: bool


class ProviderEvidencePersistenceError(RuntimeError):
    """Provider responded, but the local evidence transaction did not commit."""


async def _candidate_ids(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
) -> tuple[UUID, ...]:
    latest_versions = (
        select(
            PaymentTruthSnapshotRecord.payment_attempt_id.label("attempt_id"),
            func.max(PaymentTruthSnapshotRecord.version).label("version"),
        )
        .group_by(PaymentTruthSnapshotRecord.payment_attempt_id)
        .subquery()
    )
    latest = (
        select(PaymentTruthSnapshotRecord)
        .join(
            latest_versions,
            and_(
                PaymentTruthSnapshotRecord.payment_attempt_id == latest_versions.c.attempt_id,
                PaymentTruthSnapshotRecord.version == latest_versions.c.version,
            ),
        )
        .subquery()
    )
    result = await session.execute(
        select(PaymentAttempt.id)
        .outerjoin(latest, latest.c.payment_attempt_id == PaymentAttempt.id)
        .where(
            PaymentAttempt.provider == "razorpay",
            PaymentAttempt.provider_order_id.is_not(None),
            or_(
                latest.c.id.is_(None),
                latest.c.state.in_(
                    (
                        PaymentTruthState.OUTCOME_UNKNOWN.value,
                        PaymentTruthState.SOURCE_CONFLICT.value,
                        PaymentTruthState.MANUAL_INVESTIGATION_REQUIRED.value,
                        PaymentTruthState.PAYMENT_PENDING.value,
                    ),
                ),
                latest.c.resolved_at <= reference_time - RECONCILE_AFTER,
            ),
        )
        .order_by(PaymentAttempt.updated_at)
        .limit(batch_size),
    )
    return tuple(result.scalars())


async def _record_unavailable(
    session: AsyncSession,
    *,
    attempt: PaymentAttempt,
    error: RazorpayOrderProviderError,
    observed_at: datetime,
) -> None:
    payload: dict[str, object] = {
        "provider": "razorpay",
        "order_id": attempt.provider_order_id,
        "failure_kind": error.kind.value,
        "status_code": error.status_code,
        "retryable": error.retryable,
    }
    await record_payment_evidence(
        session,
        PaymentEvidenceWrite(
            payment_attempt_id=attempt.id,
            source=PaymentEvidenceSource.RECONCILIATION,
            source_reference=f"provider-unavailable:{observed_at.isoformat()}:{error.kind.value}",
            fact_name="provider.available",
            fact_value="false",
            content_sha256=canonical_sha256(payload),
            observed_at=observed_at,
            fresh_until=observed_at + RECONCILE_AFTER,
            normalized_fields=payload,
            verified=True,
            reliability="authoritative",
            unavailable_reason=error.kind.value,
        ),
    )
    await resolve_and_persist_payment_truth(
        session,
        payment_attempt=attempt,
        resolved_at=observed_at,
    )


def _provider_event(payment: RazorpayOrderPayment, observed_at: datetime) -> WebhookEvent:
    payload: dict[str, object] = {
        "entity": "event",
        "event": f"payment.{payment.status.value}",
        "contains": ["payment"],
        "payload": {"payment": {"entity": payment.model_dump(by_alias=True)}},
        "created_at": payment.provider_created_at,
        "reclaimrail_evidence_source": "razorpay_api_verification",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return WebhookEvent(
        id=uuid4(),
        provider="razorpay",
        provider_event_id=f"provider-api:{payment.payment_id}:{payment.status.value}",
        event_type=f"payment.{payment.status.value}",
        provider_created_at=datetime.fromtimestamp(payment.provider_created_at, tz=UTC),
        payload=payload,
        payload_sha256=hashlib.sha256(raw).hexdigest(),
        processing_status=WebhookProcessingStatus.RECEIVED.value,
        delivery_count=1,
        first_received_at=observed_at,
        last_received_at=observed_at,
    )


async def _reconcile_one(
    session: AsyncSession,
    *,
    attempt_id: UUID,
    provider: RazorpayOrderProvider,
    reference_time: datetime,
) -> str:
    attempt = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.id == attempt_id).with_for_update(),
    )
    if attempt is None or attempt.provider_order_id is None:
        return "unchanged"
    try:
        payments = await provider.fetch_order_payments(attempt.provider_order_id)
    except RazorpayOrderProviderError as error:
        await _record_unavailable(
            session,
            attempt=attempt,
            error=error,
            observed_at=reference_time,
        )
        await session.commit()
        raise

    matching = tuple(
        item
        for item in payments
        if item.order_id == attempt.provider_order_id
        and item.amount_minor == attempt.amount_minor
        and item.currency == attempt.currency
        and item.payment_id == attempt.provider_payment_id
    )
    if not matching:
        payload = {
            "order_id": attempt.provider_order_id,
            "payment_id": attempt.provider_payment_id,
            "matching_payment_count": 0,
        }
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=attempt.id,
                source=PaymentEvidenceSource.RECONCILIATION,
                source_reference=f"provider-scan:{attempt.provider_order_id}:{reference_time.isoformat()}",
                fact_name="provider.matching_payment_count",
                fact_value="0",
                content_sha256=canonical_sha256(payload),
                observed_at=reference_time,
                fresh_until=reference_time + RECONCILE_AFTER,
                normalized_fields=payload,
                verified=True,
                reliability="authoritative",
            ),
        )
        await resolve_and_persist_payment_truth(
            session, payment_attempt=attempt, resolved_at=reference_time
        )
        await session.commit()
        return "unchanged"

    payment = max(matching, key=lambda item: item.provider_created_at)
    event_id = f"provider-api:{payment.payment_id}:{payment.status.value}"
    existing = await session.scalar(
        select(WebhookEvent.id).where(
            WebhookEvent.provider == "razorpay",
            WebhookEvent.provider_event_id == event_id,
        ),
    )
    if existing is not None:
        await session.commit()
        return "unchanged"
    event = _provider_event(payment, reference_time)
    try:
        session.add(event)
        await session.flush()
        await process_canonical_payment_webhook(session, event.id, processed_at=reference_time)
        await session.commit()
    except Exception as error:
        await session.rollback()
        raise ProviderEvidencePersistenceError(
            "Provider response received but payment evidence persistence failed"
        ) from error
    return "projected"


async def reconcile_payment_truth_batch(
    session_factory: SessionFactory,
    *,
    provider: RazorpayOrderProvider,
    reference_time: datetime,
    batch_size: int,
) -> PaymentTruthReconciliationResult:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Reconciliation time must be timezone-aware")
    if not 1 <= batch_size <= 100:
        raise ValueError("Reconciliation batch size must be between 1 and 100")
    async with session_factory() as session:
        candidate_ids = await _candidate_ids(
            session, reference_time=reference_time, batch_size=batch_size
        )

    projected = unchanged = unavailable = persistence_failures = consecutive_failures = 0
    circuit_opened = False
    for attempt_id in candidate_ids:
        if consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            circuit_opened = True
            break
        try:
            async with session_factory() as session:
                outcome = await _reconcile_one(
                    session,
                    attempt_id=attempt_id,
                    provider=provider,
                    reference_time=reference_time,
                )
        except RazorpayOrderProviderError:
            unavailable += 1
            consecutive_failures += 1
            continue
        except ProviderEvidencePersistenceError:
            persistence_failures += 1
            continue
        consecutive_failures = 0
        if outcome == "projected":
            projected += 1
        else:
            unchanged += 1
    return PaymentTruthReconciliationResult(
        checked=projected + unchanged + unavailable + persistence_failures,
        projected=projected,
        unchanged=unchanged,
        unavailable=unavailable,
        persistence_failures=persistence_failures,
        circuit_opened=circuit_opened,
    )
