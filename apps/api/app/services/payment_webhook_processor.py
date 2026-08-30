from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.webhook import (
    WebhookEvent,
    WebhookProcessingStatus,
)
from app.integrations.razorpay.payment_events import (
    PaymentEventNormalizationError,
    UnsupportedPaymentEventError,
    normalize_razorpay_payment_event,
)
from app.integrations.razorpay.webhooks import (
    RazorpayWebhookEnvelope,
)
from app.services.payment_lab_webhook_correlation import (
    PaymentLabWebhookCorrelationError,
    apply_payment_lab_webhook_correlation,
    prepare_payment_lab_webhook_correlation,
)
from app.services.payment_projector import (
    PaymentProjectionConflictError,
    PaymentProjectionResult,
    project_payment_lifecycle_event,
)


class PaymentWebhookDisposition(StrEnum):
    PROJECTED = "projected"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    FAILED = "failed"


class PaymentWebhookEventNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class PaymentWebhookProcessingResult:
    webhook_event_id: UUID
    disposition: PaymentWebhookDisposition
    projection: PaymentProjectionResult | None
    error: str | None


async def lock_canonical_webhook_event(
    session: AsyncSession,
    webhook_event_id: UUID,
) -> WebhookEvent | None:
    statement = (
        select(WebhookEvent)
        .where(
            WebhookEvent.id == webhook_event_id,
        )
        .with_for_update()
    )

    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def complete_without_projection(
    session: AsyncSession,
    webhook_event: WebhookEvent,
    *,
    disposition: PaymentWebhookDisposition,
    processed_at: datetime,
    error: str | None,
) -> PaymentWebhookProcessingResult:
    webhook_event.processing_status = (
        WebhookProcessingStatus.FAILED.value
        if disposition is PaymentWebhookDisposition.FAILED
        else WebhookProcessingStatus.PROCESSED.value
    )
    webhook_event.processed_at = processed_at

    await session.flush()

    return PaymentWebhookProcessingResult(
        webhook_event_id=webhook_event.id,
        disposition=disposition,
        projection=None,
        error=error,
    )


async def process_canonical_payment_webhook(
    session: AsyncSession,
    webhook_event_id: UUID,
    *,
    processed_at: datetime,
) -> PaymentWebhookProcessingResult:
    """
    Normalize and project a canonical webhook inside the caller's transaction.

    Permanent payload failures are recorded as failed. Transient database
    failures are allowed to propagate so the worker can roll back and retry.
    """
    webhook_event = await lock_canonical_webhook_event(
        session,
        webhook_event_id,
    )

    if webhook_event is None:
        raise PaymentWebhookEventNotFoundError(
            f"Canonical webhook event was not found: {webhook_event_id}",
        )

    webhook_event.processing_status = WebhookProcessingStatus.PROCESSING.value

    if webhook_event.provider != "razorpay":
        return await complete_without_projection(
            session,
            webhook_event,
            disposition=PaymentWebhookDisposition.FAILED,
            processed_at=processed_at,
            error=(f"Unsupported webhook provider: {webhook_event.provider}"),
        )

    try:
        envelope = RazorpayWebhookEnvelope.model_validate(
            webhook_event.payload,
        )
    except ValidationError:
        return await complete_without_projection(
            session,
            webhook_event,
            disposition=PaymentWebhookDisposition.FAILED,
            processed_at=processed_at,
            error="Canonical webhook contains an invalid envelope",
        )

    try:
        lifecycle_event = normalize_razorpay_payment_event(
            webhook_event_id=webhook_event.id,
            provider_event_id=webhook_event.provider_event_id,
            envelope=envelope,
        )
    except UnsupportedPaymentEventError:
        return await complete_without_projection(
            session,
            webhook_event,
            disposition=PaymentWebhookDisposition.SKIPPED,
            processed_at=processed_at,
            error=None,
        )
    except PaymentEventNormalizationError as error:
        return await complete_without_projection(
            session,
            webhook_event,
            disposition=PaymentWebhookDisposition.FAILED,
            processed_at=processed_at,
            error=str(error),
        )

    try:
        payment_lab_correlation = await prepare_payment_lab_webhook_correlation(
            session,
            lifecycle_event,
        )
    except PaymentLabWebhookCorrelationError as error:
        return await complete_without_projection(
            session,
            webhook_event,
            disposition=PaymentWebhookDisposition.FAILED,
            processed_at=processed_at,
            error=str(error),
        )

    try:
        projection = await project_payment_lifecycle_event(
            session,
            lifecycle_event,
            processed_at=processed_at,
        )
    except PaymentProjectionConflictError as error:
        return await complete_without_projection(
            session,
            webhook_event,
            disposition=PaymentWebhookDisposition.FAILED,
            processed_at=processed_at,
            error=str(error),
        )

    if payment_lab_correlation is not None:
        apply_payment_lab_webhook_correlation(
            payment_lab_correlation,
            lifecycle_event,
            projection,
            observed_at=processed_at,
        )

    webhook_event.processing_status = WebhookProcessingStatus.PROCESSED.value

    if webhook_event.processed_at is None:
        webhook_event.processed_at = processed_at

    await session.flush()

    return PaymentWebhookProcessingResult(
        webhook_event_id=webhook_event.id,
        disposition=(
            PaymentWebhookDisposition.DUPLICATE
            if projection.duplicate
            else PaymentWebhookDisposition.PROJECTED
        ),
        projection=projection,
        error=None,
    )
