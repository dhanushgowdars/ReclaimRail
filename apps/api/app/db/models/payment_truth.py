from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentEvidenceRecord(Base):
    """Immutable fact used to reproduce a payment-truth decision."""

    __tablename__ = "payment_evidence"
    __table_args__ = (
        UniqueConstraint(
            "payment_attempt_id",
            "source",
            "source_reference",
            "fact_name",
            "content_sha256",
            name="uq_payment_evidence_fact_identity",
        ),
        CheckConstraint(
            (
                "source IN ('provider_payment_api', 'provider_order_api', "
                "'verified_webhook', 'merchant_database', 'recovery_state', "
                "'reconciliation', 'payment_lab', 'recovery_link')"
            ),
            name="ck_payment_evidence_source",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_payment_evidence_sha256",
        ),
        CheckConstraint(
            "fresh_until IS NULL OR fresh_until > observed_at",
            name="ck_payment_evidence_freshness",
        ),
        CheckConstraint(
            "reliability IN ('authoritative', 'corroborating', 'weak')",
            name="ck_payment_evidence_reliability",
        ),
        Index(
            "ix_payment_evidence_attempt_observed",
            "payment_attempt_id",
            "observed_at",
        ),
        Index(
            "ix_payment_evidence_case_observed",
            "recovery_case_id",
            "observed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    recovery_case_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    fact_name: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fresh_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    signature_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    normalized_fields: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    reliability: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="corroborating",
        server_default="corroborating",
    )
    unavailable_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PaymentTruthReconciliationState(Base):
    """Durable provider-read budget and cooldown for one payment state version."""

    __tablename__ = "payment_truth_reconciliation_state"
    __table_args__ = (
        CheckConstraint(
            "payment_state_version >= 0",
            name="ck_truth_reconciliation_payment_state_version",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_truth_reconciliation_attempt_count",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_truth_reconciliation_consecutive_failures",
        ),
        CheckConstraint(
            "observation_sequence >= 0",
            name="ck_truth_reconciliation_observation_sequence",
        ),
        CheckConstraint(
            (
                "blocked_reason IS NULL OR "
                "blocked_reason IN ('controlled_synthetic', 'retry_budget_exhausted')"
            ),
            name="ck_truth_reconciliation_blocked_reason",
        ),
        Index(
            "ix_truth_reconciliation_retry",
            "next_retry_at",
            "circuit_open_until",
        ),
    )

    payment_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    payment_state_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    observation_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    circuit_open_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    exhausted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    blocked_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
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


class PaymentTruthSnapshotRecord(Base):
    """Append-only, versioned result produced from payment evidence."""

    __tablename__ = "payment_truth_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "payment_attempt_id",
            "version",
            name="uq_payment_truth_attempt_version",
        ),
        UniqueConstraint(
            "payment_attempt_id",
            "evidence_digest",
            "state",
            name="uq_payment_truth_attempt_digest_state",
        ),
        CheckConstraint("version >= 1", name="ck_payment_truth_version"),
        CheckConstraint(
            (
                "state IN ('payment_confirmed', 'payment_failed', 'payment_pending', "
                "'outcome_unknown', 'source_conflict', 'late_authorization', "
                "'recovery_already_active', 'recovery_confirmed', "
                "'manual_investigation_required')"
            ),
            name="ck_payment_truth_state",
        ),
        CheckConstraint(
            "evidence_digest ~ '^[0-9a-f]{64}$'",
            name="ck_payment_truth_evidence_digest",
        ),
        Index(
            "ix_payment_truth_attempt_resolved",
            "payment_attempt_id",
            "resolved_at",
        ),
        Index(
            "ix_payment_truth_case_resolved",
            "recovery_case_id",
            "resolved_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    recovery_case_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    conflict_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(32), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
