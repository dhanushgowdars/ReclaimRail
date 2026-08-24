from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.webhook import (
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEvent,
    WebhookProcessingStatus,
    WebhookSignatureStatus,
)
from app.integrations.razorpay.webhooks import (
    RazorpayWebhookEnvelope,
    compute_payload_sha256,
    compute_signature_sha256,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class WebhookIngestionResult:
    canonical_event_id: UUID
    provider_event_id: str
    duplicate: bool


def provider_timestamp_to_datetime(timestamp: int) -> datetime:
    return EPOCH + timedelta(seconds=timestamp)


async def ingest_verified_webhook(
    session: AsyncSession,
    *,
    provider_event_id: str,
    signature: str,
    raw_body: bytes,
    envelope: RazorpayWebhookEnvelope,
) -> WebhookIngestionResult:
    received_at = datetime.now(UTC)
    payload_sha256 = compute_payload_sha256(raw_body)
    signature_sha256 = compute_signature_sha256(signature)
    payload: dict[str, object] = envelope.model_dump(mode="json")

    try:
        event_insert = (
            insert(WebhookEvent)
            .values(
                provider="razorpay",
                provider_event_id=provider_event_id,
                event_type=envelope.event,
                account_id=envelope.account_id,
                provider_created_at=provider_timestamp_to_datetime(
                    envelope.created_at,
                ),
                payload=payload,
                payload_sha256=payload_sha256,
                processing_status=WebhookProcessingStatus.RECEIVED.value,
                delivery_count=1,
                first_received_at=received_at,
                last_received_at=received_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_webhook_events_provider_event_id",
            )
            .returning(WebhookEvent.id)
        )

        insert_result = await session.execute(event_insert)
        canonical_event_id: UUID | None = insert_result.scalar_one_or_none()
        duplicate = canonical_event_id is None

        if duplicate:
            event_update = (
                update(WebhookEvent)
                .where(
                    WebhookEvent.provider == "razorpay",
                    WebhookEvent.provider_event_id == provider_event_id,
                )
                .values(
                    delivery_count=WebhookEvent.delivery_count + 1,
                    last_received_at=received_at,
                )
                .returning(WebhookEvent.id)
            )

            update_result = await session.execute(event_update)
            canonical_event_id = update_result.scalar_one()

        if canonical_event_id is None:
            raise RuntimeError(
                "Unable to resolve canonical webhook event",
            )

        delivery = WebhookDelivery(
            canonical_event_id=canonical_event_id,
            provider="razorpay",
            provider_event_id=provider_event_id,
            event_type=envelope.event,
            raw_payload=raw_body,
            payload_sha256=payload_sha256,
            payload_size_bytes=len(raw_body),
            signature_sha256=signature_sha256,
            signature_status=WebhookSignatureStatus.VERIFIED.value,
            delivery_status=(
                WebhookDeliveryStatus.DUPLICATE.value
                if duplicate
                else WebhookDeliveryStatus.ACCEPTED.value
            ),
            is_duplicate=duplicate,
            response_status_code=200 if duplicate else 202,
            received_at=received_at,
        )

        session.add(delivery)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return WebhookIngestionResult(
        canonical_event_id=canonical_event_id,
        provider_event_id=provider_event_id,
        duplicate=duplicate,
    )


async def record_rejected_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    provider_event_id: str | None,
    signature: str | None,
    signature_status: WebhookSignatureStatus,
    rejection_reason: str,
    response_status_code: int,
    event_type: str | None = None,
) -> None:
    delivery = WebhookDelivery(
        provider="razorpay",
        provider_event_id=provider_event_id,
        event_type=event_type,
        raw_payload=raw_body,
        payload_sha256=compute_payload_sha256(raw_body),
        payload_size_bytes=len(raw_body),
        signature_sha256=(compute_signature_sha256(signature) if signature is not None else None),
        signature_status=signature_status.value,
        delivery_status=WebhookDeliveryStatus.REJECTED.value,
        is_duplicate=False,
        rejection_reason=rejection_reason,
        response_status_code=response_status_code,
        received_at=datetime.now(UTC),
    )

    try:
        session.add(delivery)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
