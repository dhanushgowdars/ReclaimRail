"""Durable reviewer-safe transcript for the Phase 17 investigator."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecoveryInvestigationSession(Base):
    __tablename__ = "recovery_investigation_sessions"
    __table_args__ = (
        UniqueConstraint("recovery_case_id", "case_version", name="uq_investigation_case_version"),
        CheckConstraint(
            "status IN ('running','completed','abstained','fallback','failed_safe')",
            name="ck_investigation_session_status",
        ),
        CheckConstraint("case_version >= 0", name="ck_investigation_case_version"),
        CheckConstraint("truth_version >= 1", name="ck_investigation_truth_version"),
        CheckConstraint("max_tool_calls >= 1", name="ck_investigation_tool_budget"),
        CheckConstraint("max_model_retries >= 0", name="ck_investigation_retry_budget"),
        CheckConstraint("max_total_tokens >= 256", name="ck_investigation_token_budget"),
        CheckConstraint("max_duration_ms >= 1000", name="ck_investigation_duration_budget"),
        CheckConstraint("tool_call_count >= 0", name="ck_investigation_tool_count"),
        Index("ix_investigation_case_started", "recovery_case_id", "started_at"),
        Index("ix_investigation_status_started", "status", "started_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    recovery_case_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    truth_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_truth_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    truth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="running", server_default="running"
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_registry_version: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow_mode: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    max_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    max_model_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    input_token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    terminal_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RecoveryInvestigationStep(Base):
    __tablename__ = "recovery_investigation_steps"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_number", name="uq_investigation_step_sequence"),
        CheckConstraint("sequence_number >= 1", name="ck_investigation_step_sequence"),
        CheckConstraint(
            "outcome IN ('succeeded','unavailable','rejected','failed')",
            name="ck_investigation_step_outcome",
        ),
        CheckConstraint("cumulative_tool_calls >= 1", name="ck_investigation_step_tool_count"),
        CheckConstraint("cumulative_total_tokens >= 0", name="ck_investigation_step_tokens"),
        CheckConstraint("elapsed_ms >= 0", name="ck_investigation_step_elapsed"),
        Index("ix_investigation_steps_session_sequence", "session_id", "sequence_number"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recovery_investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    output_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_response_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cumulative_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecoveryInvestigationHypothesis(Base):
    __tablename__ = "recovery_investigation_hypotheses"
    __table_args__ = (
        UniqueConstraint("session_id", "hypothesis_key", name="uq_investigation_hypothesis_key"),
        CheckConstraint(
            "status IN ('open','supported','contradicted','unresolved','rejected')",
            name="ck_investigation_hypothesis_status",
        ),
        CheckConstraint("first_step >= 0", name="ck_investigation_hypothesis_first_step"),
        CheckConstraint("last_step >= first_step", name="ck_investigation_hypothesis_last_step"),
        CheckConstraint("version >= 1", name="ck_investigation_hypothesis_version"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recovery_investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    hypothesis_key: Mapped[str] = mapped_column(String(80), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    contradicting_evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    missing_questions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    next_observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_step: Mapped[int] = mapped_column(Integer, nullable=False)
    last_step: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
