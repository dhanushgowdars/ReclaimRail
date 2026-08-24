from typing import Annotated, Literal, Never
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.db.models.webhook import WebhookSignatureStatus
from app.integrations.razorpay.webhooks import (
    MAX_WEBHOOK_BODY_BYTES,
    parse_webhook_envelope,
    verify_webhook_signature,
)
from app.services.webhook_ingestion import (
    ingest_verified_webhook,
    record_rejected_webhook,
)

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]
RazorpaySignatureHeader = Annotated[
    str | None,
    Header(alias="X-Razorpay-Signature"),
]
RazorpayEventIdHeader = Annotated[
    str | None,
    Header(alias="X-Razorpay-Event-Id"),
]

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
)


class WebhookReceiptResponse(BaseModel):
    status: Literal["accepted", "duplicate"]
    event_id: UUID
    provider_event_id: str


async def read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")

    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            ) from error

        if declared_size < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            )

        if declared_size > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload is too large",
            )

    body = bytearray()

    async for chunk in request.stream():
        body.extend(chunk)

        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload is too large",
            )

    return bytes(body)


async def reject_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    provider_event_id: str | None,
    signature: str | None,
    signature_status: WebhookSignatureStatus,
    rejection_reason: str,
    response_status_code: int,
    event_type: str | None = None,
) -> Never:
    await record_rejected_webhook(
        session,
        raw_body=raw_body,
        provider_event_id=provider_event_id,
        signature=signature,
        signature_status=signature_status,
        rejection_reason=rejection_reason,
        response_status_code=response_status_code,
        event_type=event_type,
    )

    raise HTTPException(
        status_code=response_status_code,
        detail="Webhook rejected",
    )


@router.post(
    "/razorpay",
    response_model=WebhookReceiptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a Razorpay webhook",
)
async def receive_razorpay_webhook(
    request: Request,
    response: Response,
    settings: SettingsDependency,
    session: DatabaseSessionDependency,
    signature: RazorpaySignatureHeader = None,
    provider_event_id: RazorpayEventIdHeader = None,
) -> WebhookReceiptResponse:
    configured_secret = settings.razorpay_webhook_secret

    if configured_secret is None or not configured_secret.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook verification is unavailable",
        )

    raw_body = await read_limited_body(request)

    if signature is None:
        await reject_webhook(
            session,
            raw_body=raw_body,
            provider_event_id=provider_event_id,
            signature=None,
            signature_status=WebhookSignatureStatus.MISSING,
            rejection_reason="missing_signature",
            response_status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not verify_webhook_signature(
        raw_body,
        signature,
        configured_secret.get_secret_value(),
    ):
        await reject_webhook(
            session,
            raw_body=raw_body,
            provider_event_id=provider_event_id,
            signature=signature,
            signature_status=WebhookSignatureStatus.INVALID,
            rejection_reason="invalid_signature",
            response_status_code=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        envelope = parse_webhook_envelope(raw_body)
    except ValidationError:
        await reject_webhook(
            session,
            raw_body=raw_body,
            provider_event_id=provider_event_id,
            signature=signature,
            signature_status=WebhookSignatureStatus.VERIFIED,
            rejection_reason="invalid_payload",
            response_status_code=status.HTTP_400_BAD_REQUEST,
        )

    if provider_event_id is None or not provider_event_id.strip() or len(provider_event_id) > 128:
        await reject_webhook(
            session,
            raw_body=raw_body,
            provider_event_id=provider_event_id,
            signature=signature,
            signature_status=WebhookSignatureStatus.VERIFIED,
            rejection_reason="invalid_event_id",
            response_status_code=status.HTTP_400_BAD_REQUEST,
            event_type=envelope.event,
        )

    normalized_event_id = provider_event_id.strip()

    result = await ingest_verified_webhook(
        session,
        provider_event_id=normalized_event_id,
        signature=signature,
        raw_body=raw_body,
        envelope=envelope,
    )

    if result.duplicate:
        response.status_code = status.HTTP_200_OK
        receipt_status: Literal["accepted", "duplicate"] = "duplicate"
    else:
        receipt_status = "accepted"

    return WebhookReceiptResponse(
        status=receipt_status,
        event_id=result.canonical_event_id,
        provider_event_id=result.provider_event_id,
    )
