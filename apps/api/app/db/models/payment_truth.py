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
