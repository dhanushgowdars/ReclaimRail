from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebhookSignatureStatus(StrEnum):
    VERIFIED = "verified"
    INVALID = "invalid"
    MISSING = "missing"


class WebhookDeliveryStatus(StrEnum):
    RECEIVED = "received"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"


class WebhookProcessingStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_webhook_events_provider_event_id",
        ),
        CheckConstraint(
            "processing_status IN ('received', 'queued', 'processing', 'processed', 'failed')",
            name="ck_webhook_events_processing_status",
        ),
        Index(
            "ix_webhook_events_type_created",
            "event_type",
            "provider_created_at",
        ),
        Index(
            "ix_webhook_events_status_received",
            "processing_status",
            "first_received_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="razorpay",
        server_default="razorpay",
    )
    provider_event_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    account_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    processing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=WebhookProcessingStatus.RECEIVED.value,
        server_default=WebhookProcessingStatus.RECEIVED.value,
    )
    delivery_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    first_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint(
            "signature_status IN ('verified', 'invalid', 'missing')",
            name="ck_webhook_deliveries_signature_status",
        ),
        CheckConstraint(
            "delivery_status IN ('received', 'accepted', 'duplicate', 'rejected', 'failed')",
            name="ck_webhook_deliveries_delivery_status",
        ),
        CheckConstraint(
            "payload_size_bytes >= 0",
            name="ck_webhook_deliveries_payload_size",
        ),
        CheckConstraint(
            "response_status_code IS NULL OR response_status_code BETWEEN 100 AND 599",
            name="ck_webhook_deliveries_response_status",
        ),
        Index(
            "ix_webhook_deliveries_event_received",
            "provider_event_id",
            "received_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    canonical_event_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "webhook_events.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="razorpay",
        server_default="razorpay",
    )
    provider_event_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    event_type: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    raw_payload: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    payload_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    signature_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    signature_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=WebhookSignatureStatus.MISSING.value,
        server_default=WebhookSignatureStatus.MISSING.value,
    )
    delivery_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=WebhookDeliveryStatus.RECEIVED.value,
        server_default=WebhookDeliveryStatus.RECEIVED.value,
    )
    is_duplicate: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=false(),
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    response_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
