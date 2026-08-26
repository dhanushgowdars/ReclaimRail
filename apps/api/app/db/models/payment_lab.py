from datetime import datetime
from enum import StrEnum
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
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentLabRunMode(StrEnum):
    GUIDED = "guided"
    CUSTOM = "custom"
    REPLAY = "replay"


class PaymentLabRunProvenance(StrEnum):
    RAZORPAY_TEST = "razorpay_test"
    VERIFIED_REPLAY = "verified_replay"


class PaymentLabRunStatus(StrEnum):
    CREATING = "creating"
    CHECKOUT_READY = "checkout_ready"
    PAYMENT_ATTEMPTED = "payment_attempted"
    RECOVERY_RUNNING = "recovery_running"
    COMPLETED = "completed"
    PROVIDER_FAILED = "provider_failed"
    EXPIRED = "expired"


class PaymentLabRun(Base):
    """PII-free control record for one reviewer-initiated Test Mode run."""

    __tablename__ = "payment_lab_runs"
    __table_args__ = (
        UniqueConstraint(
            "client_request_id",
            name="uq_payment_lab_runs_client_request_id",
        ),
        UniqueConstraint(
            "provider_order_id",
            name="uq_payment_lab_runs_provider_order_id",
        ),
        UniqueConstraint(
            "payment_attempt_id",
            name="uq_payment_lab_runs_payment_attempt_id",
        ),
        CheckConstraint(
            "mode IN ('guided', 'custom', 'replay')",
            name="ck_payment_lab_runs_mode",
        ),
        CheckConstraint(
            "provenance IN ('razorpay_test', 'verified_replay')",
            name="ck_payment_lab_runs_provenance",
        ),
        CheckConstraint(
            (
                "status IN ("
                "'creating', 'checkout_ready', 'payment_attempted', "
                "'recovery_running', 'completed', 'provider_failed', 'expired'"
                ")"
            ),
            name="ck_payment_lab_runs_status",
        ),
        CheckConstraint(
            "amount_minor > 0",
            name="ck_payment_lab_runs_amount_minor",
        ),
        CheckConstraint(
            "char_length(currency) = 3",
            name="ck_payment_lab_runs_currency",
        ),
        CheckConstraint(
            "payment_method IN ('upi', 'card', 'netbanking', 'wallet')",
            name="ck_payment_lab_runs_payment_method",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_payment_lab_runs_version",
        ),
        CheckConstraint(
            (
                "(status = 'checkout_ready' AND provider_order_id IS NOT NULL) "
                "OR status <> 'checkout_ready'"
            ),
            name="ck_payment_lab_runs_ready_order",
        ),
        Index(
            "ix_payment_lab_runs_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_payment_lab_runs_provenance_created",
            "provenance",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    client_request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    provenance: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        server_default=PaymentLabRunProvenance.RAZORPAY_TEST.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PaymentLabRunStatus.CREATING.value,
        server_default=PaymentLabRunStatus.CREATING.value,
    )

    amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    receipt: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
    )

    provider_order_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_order_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    payment_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "payment_attempts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    failure_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    checkout_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
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
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
