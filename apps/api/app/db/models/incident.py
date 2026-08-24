from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RevenueIncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class IncidentObservationOutcome(StrEnum):
    NORMAL = "normal"
    INSUFFICIENT_DATA = "insufficient_data"
    INCIDENT = "incident"


class RevenueIncident(Base):
    """Current lifecycle projection of a detected revenue incident."""

    __tablename__ = "revenue_incidents"
    __table_args__ = (
        CheckConstraint(
            ("status IN ('open', 'investigating', 'mitigating', 'resolved', 'dismissed')"),
            name="ck_revenue_incidents_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_revenue_incidents_severity",
        ),
        CheckConstraint(
            "scope IN ('global', 'payment_method', 'error_signature')",
            name="ck_revenue_incidents_scope",
        ),
        CheckConstraint(
            "total_attempts >= 0",
            name="ck_revenue_incidents_total_attempts",
        ),
        CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= total_attempts",
            name="ck_revenue_incidents_failed_attempts",
        ),
        CheckConstraint(
            "total_amount_minor >= 0",
            name="ck_revenue_incidents_total_amount",
        ),
        CheckConstraint(
            ("revenue_at_risk_minor >= 0 AND revenue_at_risk_minor <= total_amount_minor"),
            name="ck_revenue_incidents_revenue_at_risk",
        ),
        CheckConstraint(
            "failure_rate BETWEEN 0 AND 1",
            name="ck_revenue_incidents_failure_rate",
        ),
        CheckConstraint(
            "baseline_failure_rate BETWEEN 0 AND 1",
            name="ck_revenue_incidents_baseline_rate",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_revenue_incidents_confidence",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="ck_revenue_incidents_occurrence_count",
        ),
        CheckConstraint(
            "current_window_end > current_window_start",
            name="ck_revenue_incidents_window",
        ),
        CheckConstraint(
            (
                "("
                "status IN ('resolved', 'dismissed') "
                "AND resolved_at IS NOT NULL"
                ") OR ("
                "status IN ('open', 'investigating', 'mitigating') "
                "AND resolved_at IS NULL"
                ")"
            ),
            name="ck_revenue_incidents_resolution",
        ),
        Index(
            "ix_revenue_incidents_active_queue",
            "status",
            "severity",
            "last_detected_at",
        ),
        Index(
            "ix_revenue_incidents_scope_detected",
            "scope",
            "dimension_value",
            "last_detected_at",
        ),
        Index(
            "uq_revenue_incidents_active_fingerprint",
            "fingerprint",
            "currency",
            unique=True,
            postgresql_where=text("status IN ('open', 'investigating', 'mitigating')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    fingerprint: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    dimension_value: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RevenueIncidentStatus.OPEN.value,
        server_default=RevenueIncidentStatus.OPEN.value,
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    current_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    current_window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    total_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    failed_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    total_amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    revenue_at_risk_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    failure_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    baseline_failure_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    absolute_uplift: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    rate_multiplier: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    robust_z_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolution_reason: Mapped[str | None] = mapped_column(
        Text,
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


class IncidentDetectionObservation(Base):
    """Immutable evidence produced by one detector evaluation."""

    __tablename__ = "incident_detection_observations"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint",
            "currency",
            "window_start",
            "window_end",
            "detector_version",
            name="uq_incident_observations_window_version",
        ),
        CheckConstraint(
            "outcome IN ('normal', 'insufficient_data', 'incident')",
            name="ck_incident_observations_outcome",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_incident_observations_severity",
        ),
        CheckConstraint(
            "scope IN ('global', 'payment_method', 'error_signature')",
            name="ck_incident_observations_scope",
        ),
        CheckConstraint(
            (
                "("
                "outcome = 'incident' "
                "AND severity IS NOT NULL "
                "AND incident_id IS NOT NULL"
                ") OR ("
                "outcome IN ('normal', 'insufficient_data') "
                "AND severity IS NULL"
                ")"
            ),
            name="ck_incident_observations_decision",
        ),
        CheckConstraint(
            "baseline_window_count >= 0",
            name="ck_incident_observations_baseline_count",
        ),
        CheckConstraint(
            "total_attempts >= 0",
            name="ck_incident_observations_total_attempts",
        ),
        CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= total_attempts",
            name="ck_incident_observations_failed_attempts",
        ),
        CheckConstraint(
            "total_amount_minor >= 0",
            name="ck_incident_observations_total_amount",
        ),
        CheckConstraint(
            ("revenue_at_risk_minor >= 0 AND revenue_at_risk_minor <= total_amount_minor"),
            name="ck_incident_observations_revenue_at_risk",
        ),
        CheckConstraint(
            "failure_rate BETWEEN 0 AND 1",
            name="ck_incident_observations_failure_rate",
        ),
        CheckConstraint(
            ("baseline_failure_rate IS NULL OR baseline_failure_rate BETWEEN 0 AND 1"),
            name="ck_incident_observations_baseline_rate",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_incident_observations_confidence",
        ),
        CheckConstraint(
            "window_end > window_start",
            name="ck_incident_observations_window",
        ),
        Index(
            "ix_incident_observations_outcome_detected",
            "outcome",
            "detected_at",
        ),
        Index(
            "ix_incident_observations_incident_detected",
            "incident_id",
            "detected_at",
        ),
        Index(
            "ix_incident_observations_run_detected",
            "detector_run_id",
            "detected_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    detector_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        default=uuid4,
    )
    incident_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "revenue_incidents.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    detector_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="robust-mad-v1",
        server_default="robust-mad-v1",
    )
    fingerprint: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    dimension_value: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )

    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    severity: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    baseline_window_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    total_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    failed_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    total_amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    revenue_at_risk_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    failure_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    baseline_failure_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    mad_failure_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    absolute_uplift: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    rate_multiplier: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    robust_z_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    reason_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
