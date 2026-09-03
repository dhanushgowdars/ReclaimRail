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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvaluationRun(Base):
    """A controlled, non-production recovery evaluation cohort."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_evaluation_runs_run_key"),
        CheckConstraint(
            "provenance = 'controlled_synthetic'", name="ck_evaluation_runs_provenance"
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), nullable=False, default="controlled_synthetic"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    scenario_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvaluationScenario(Base):
    """Immutable result of evaluating one synthetic payment scenario."""

    __tablename__ = "evaluation_scenarios"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id", "scenario_number", name="uq_evaluation_scenarios_run_number"
        ),
        CheckConstraint("scenario_number >= 1", name="ck_evaluation_scenarios_number"),
        CheckConstraint("original_amount_minor > 0", name="ck_evaluation_scenarios_amount"),
        CheckConstraint("recovered_minor >= 0", name="ck_evaluation_scenarios_recovered"),
        CheckConstraint("pending_minor >= 0", name="ck_evaluation_scenarios_pending"),
        CheckConstraint("protected_minor >= 0", name="ck_evaluation_scenarios_protected"),
        Index("ix_evaluation_scenarios_run_outcome", "evaluation_run_id", "outcome"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    evaluation_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    original_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    at_risk: Mapped[bool] = mapped_column(nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False)
    attempted: Mapped[bool] = mapped_column(nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_condition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_recommendation: Mapped[str | None] = mapped_column(String(160), nullable=True)
    proposed_action: Mapped[str | None] = mapped_column(String(48), nullable=True)
    expected_policy_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    policy_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_explanation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    execution_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guardrails: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    recovered_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    control_recovered_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pending_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    protected_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    decision_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
