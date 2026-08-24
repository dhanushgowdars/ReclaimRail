from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentAttempt(Base):
    """Current provider-independent projection of a payment."""

    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_payment_id",
            name="uq_payment_attempts_provider_payment_id",
        ),
        CheckConstraint(
            (
                "current_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_attempts_current_state",
        ),
        CheckConstraint(
            "amount_minor >= 0",
            name="ck_payment_attempts_amount_minor",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_payment_attempts_state_version",
        ),
        CheckConstraint(
            "NOT recovery_eligible OR current_state = 'failed'",
            name="ck_payment_attempts_recovery_eligible",
        ),
        Index(
            "ix_payment_attempts_state_updated",
            "current_state",
            "updated_at",
        ),
        Index(
            "ix_payment_attempts_recovery_queue",
            "recovery_eligible",
            "updated_at",
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
    provider_payment_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    account_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_order_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    method: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    payment_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    current_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    state_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    state_provider_event_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    state_webhook_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "webhook_events.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    state_event_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    error_description: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    error_source: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    error_step: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    error_reason: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    recovery_eligible: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=false(),
    )
    recovery_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    recovery_stop_reason: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    late_authorization_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaymentStateTransition(Base):
    """Immutable audit record for one processed payment lifecycle event."""

    __tablename__ = "payment_state_transitions"
    __table_args__ = (
        UniqueConstraint(
            "webhook_event_id",
            name="uq_payment_state_transitions_webhook_event_id",
        ),
        CheckConstraint(
            (
                "previous_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_state_transitions_previous_state",
        ),
        CheckConstraint(
            (
                "incoming_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_state_transitions_incoming_state",
        ),
        CheckConstraint(
            (
                "resulting_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_state_transitions_resulting_state",
        ),
        CheckConstraint(
            "outcome IN ('applied', 'ignored')",
            name="ck_payment_state_transitions_outcome",
        ),
        CheckConstraint(
            "resulting_version >= 0",
            name="ck_payment_state_transitions_resulting_version",
        ),
        Index(
            "ix_payment_state_transitions_attempt_processed",
            "payment_attempt_id",
            "processed_at",
        ),
        Index(
            "ix_payment_state_transitions_outcome_processed",
            "outcome",
            "processed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "payment_attempts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    webhook_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "webhook_events.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    provider_event_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    previous_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    incoming_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    resulting_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    resulting_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    outcome: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    late_authorization: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=false(),
    )
    stop_recovery: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=false(),
    )
    event_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
