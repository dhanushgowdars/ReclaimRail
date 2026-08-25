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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecoveryOutcomeStatus(StrEnum):
    PAYMENT_LINK_PENDING = "payment_link_pending"
    RECOVERED = "recovered"
    PAYMENT_LINK_EXPIRED = "payment_link_expired"
    PAYMENT_LINK_CANCELLED = "payment_link_cancelled"
    DUPLICATE_COLLECTION_PREVENTED = "duplicate_collection_prevented"
    REVERSED = "reversed"
    UNRESOLVED = "unresolved"


class RecoveryOutcomeAttribution(StrEnum):
    DIRECT_PAYMENT_LINK = "direct_payment_link"
    LATE_AUTHORIZATION_SAFETY = "late_authorization_safety"
    NONE = "none"


class RecoveryOutcome(Base):
    """
    Current, idempotent financial-outcome projection for one recovery case.

    This table contains no customer PII. Evidence references point to
    provider/webhook/audit identifiers only.
    """

    __tablename__ = "recovery_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "recovery_case_id",
            name="uq_recovery_outcomes_recovery_case_id",
        ),
        CheckConstraint(
            (
                "status IN ("
                "'payment_link_pending', "
                "'recovered', "
                "'payment_link_expired', "
                "'payment_link_cancelled', "
                "'duplicate_collection_prevented', "
                "'reversed', "
                "'unresolved'"
                ")"
            ),
            name="ck_recovery_outcomes_status",
        ),
        CheckConstraint(
            ("attribution IN ('direct_payment_link', 'late_authorization_safety', 'none')"),
            name="ck_recovery_outcomes_attribution",
        ),
        CheckConstraint(
            "original_amount_minor > 0",
            name="ck_recovery_outcomes_original_amount",
        ),
        CheckConstraint(
            "gross_recovered_minor >= 0",
            name="ck_recovery_outcomes_gross_recovered",
        ),
        CheckConstraint(
            "reversed_minor >= 0",
            name="ck_recovery_outcomes_reversed",
        ),
        CheckConstraint(
            "duplicate_collection_prevented_minor >= 0",
            name="ck_recovery_outcomes_duplicate_prevented",
        ),
        CheckConstraint(
            "gross_recovered_minor <= original_amount_minor",
            name="ck_recovery_outcomes_gross_within_original",
        ),
        CheckConstraint(
            "reversed_minor <= gross_recovered_minor",
            name="ck_recovery_outcomes_reversal_within_gross",
        ),
        CheckConstraint(
            ("duplicate_collection_prevented_minor <= original_amount_minor"),
            name="ck_recovery_outcomes_prevented_within_original",
        ),
        CheckConstraint(
            (
                "(status = 'recovered' "
                "AND gross_recovered_minor > 0 "
                "AND attribution = 'direct_payment_link' "
                "AND recovery_action_id IS NOT NULL "
                "AND payment_link_id IS NOT NULL) "
                "OR (status = 'reversed' "
                "AND gross_recovered_minor > 0 "
                "AND reversed_minor > 0 "
                "AND attribution = 'direct_payment_link' "
                "AND recovery_action_id IS NOT NULL "
                "AND payment_link_id IS NOT NULL) "
                "OR (status = 'duplicate_collection_prevented' "
                "AND gross_recovered_minor = 0 "
                "AND reversed_minor = 0 "
                "AND duplicate_collection_prevented_minor > 0 "
                "AND attribution = 'late_authorization_safety') "
                "OR (status IN ("
                "'payment_link_pending', "
                "'payment_link_expired', "
                "'payment_link_cancelled', "
                "'unresolved'"
                ") "
                "AND gross_recovered_minor = 0 "
                "AND reversed_minor = 0 "
                "AND duplicate_collection_prevented_minor = 0 "
                "AND attribution = 'none')"
            ),
            name="ck_recovery_outcomes_financial_semantics",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_recovery_outcomes_version",
        ),
        CheckConstraint(
            "char_length(outcome_fingerprint) = 64",
            name="ck_recovery_outcomes_fingerprint_length",
        ),
        Index(
            "ix_recovery_outcomes_status_updated",
            "status",
            "updated_at",
        ),
        Index(
            "ix_recovery_outcomes_payment_attempt",
            "payment_attempt_id",
        ),
        Index(
            "ix_recovery_outcomes_payment_link",
            "payment_link_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    recovery_case_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_cases.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "payment_attempts.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    recovery_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_actions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    provider_payment_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    payment_link_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_outcome_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
    )
    attribution: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
    )

    original_amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    gross_recovered_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    reversed_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    duplicate_collection_prevented_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    evidence_event_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    outcome_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )


class RecoveryOutcomeObservation(Base):
    """
    Immutable reconciliation history for a RecoveryOutcome projection.

    The unique fingerprint makes replayed provider events idempotent.
    """

    __tablename__ = "recovery_outcome_observations"
    __table_args__ = (
        UniqueConstraint(
            "recovery_outcome_id",
            "observation_fingerprint",
            name=("uq_recovery_outcome_observations_outcome_fingerprint"),
        ),
        CheckConstraint(
            (
                "status IN ("
                "'payment_link_pending', "
                "'recovered', "
                "'payment_link_expired', "
                "'payment_link_cancelled', "
                "'duplicate_collection_prevented', "
                "'reversed', "
                "'unresolved'"
                ")"
            ),
            name="ck_recovery_outcome_observations_status",
        ),
        CheckConstraint(
            ("attribution IN ('direct_payment_link', 'late_authorization_safety', 'none')"),
            name="ck_recovery_outcome_observations_attribution",
        ),
        CheckConstraint(
            "gross_recovered_minor >= 0",
            name="ck_recovery_outcome_observations_gross_recovered",
        ),
        CheckConstraint(
            "reversed_minor >= 0",
            name="ck_recovery_outcome_observations_reversed",
        ),
        CheckConstraint(
            "duplicate_collection_prevented_minor >= 0",
            name=("ck_recovery_outcome_observations_duplicate_prevented"),
        ),
        CheckConstraint(
            "reversed_minor <= gross_recovered_minor",
            name=("ck_recovery_outcome_observations_reversal_within_gross"),
        ),
        CheckConstraint(
            "char_length(observation_fingerprint) = 64",
            name=("ck_recovery_outcome_observations_fingerprint_length"),
        ),
        Index(
            "ix_recovery_outcome_observations_outcome_occurred",
            "recovery_outcome_id",
            "occurred_at",
        ),
        Index(
            "ix_recovery_outcome_observations_status_occurred",
            "status",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    recovery_outcome_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_outcomes.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    recovery_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_actions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
    )
    attribution: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
    )

    gross_recovered_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    reversed_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    duplicate_collection_prevented_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    payment_link_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_outcome_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    evidence_event_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    observation_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now,
        server_default=func.now(),
    )
