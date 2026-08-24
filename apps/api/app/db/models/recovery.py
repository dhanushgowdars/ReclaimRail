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
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.recovery import RecoveryCaseStatus


class RecoveryAgentRunStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class RecoveryPlannerProvider(StrEnum):
    DETERMINISTIC = "deterministic"
    GEMINI = "gemini"


class RecoveryActionStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    STOPPED = "stopped"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecoveryAuditActor(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"
    POLICY = "policy"
    WORKER = "worker"
    OPERATOR = "operator"
    RAZORPAY = "razorpay"


class RecoveryCase(Base):
    """Current projection of one bounded payment-recovery case."""

    __tablename__ = "recovery_cases"
    __table_args__ = (
        UniqueConstraint(
            "payment_attempt_id",
            name="uq_recovery_cases_payment_attempt_id",
        ),
        CheckConstraint(
            (
                "status IN "
                "('open', 'planning', 'ready', 'executing', "
                "'waiting', 'recovered', 'exhausted', "
                "'cancelled', 'escalated')"
            ),
            name="ck_recovery_cases_status",
        ),
        CheckConstraint(
            "amount_minor > 0",
            name="ck_recovery_cases_amount_minor",
        ),
        CheckConstraint(
            "recovery_attempt_count >= 0",
            name="ck_recovery_cases_attempt_count",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_recovery_cases_version",
        ),
        CheckConstraint(
            (
                "(status = 'recovered' "
                "AND recovered_at IS NOT NULL "
                "AND closed_at IS NOT NULL) "
                "OR (status IN ('exhausted', 'cancelled') "
                "AND recovered_at IS NULL "
                "AND closed_at IS NOT NULL) "
                "OR (status IN "
                "('open', 'planning', 'ready', 'executing', "
                "'waiting', 'escalated') "
                "AND recovered_at IS NULL "
                "AND closed_at IS NULL)"
            ),
            name="ck_recovery_cases_lifecycle",
        ),
        Index(
            "ix_recovery_cases_work_queue",
            "status",
            "next_action_at",
            "updated_at",
        ),
        Index(
            "ix_recovery_cases_incident_status",
            "source_incident_id",
            "status",
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
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_incident_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "revenue_incidents.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RecoveryCaseStatus.OPEN.value,
        server_default=RecoveryCaseStatus.OPEN.value,
    )
    amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    payment_method: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    recovery_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    customer_contact_allowed: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=false(),
    )

    active_payment_link_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    last_customer_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    late_authorization_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    close_reason: Mapped[str | None] = mapped_column(
        String(255),
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


class RecoveryAgentRun(Base):
    """Auditable execution record for one bounded planner invocation."""

    __tablename__ = "recovery_agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "recovery_case_id",
            "run_number",
            name="uq_recovery_agent_runs_case_number",
        ),
        CheckConstraint(
            "run_number >= 1",
            name="ck_recovery_agent_runs_number",
        ),
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'superseded')",
            name="ck_recovery_agent_runs_status",
        ),
        CheckConstraint(
            "planner_provider IN ('deterministic', 'gemini')",
            name="ck_recovery_agent_runs_provider",
        ),
        CheckConstraint(
            "proposed_action_count >= 0",
            name="ck_recovery_agent_runs_action_count",
        ),
        CheckConstraint(
            "input_token_count IS NULL OR input_token_count >= 0",
            name="ck_recovery_agent_runs_input_tokens",
        ),
        CheckConstraint(
            "output_token_count IS NULL OR output_token_count >= 0",
            name="ck_recovery_agent_runs_output_tokens",
        ),
        CheckConstraint(
            (
                "(status = 'started' "
                "AND completed_at IS NULL "
                "AND failure_message IS NULL) "
                "OR (status IN ('succeeded', 'superseded') "
                "AND completed_at IS NOT NULL "
                "AND failure_message IS NULL) "
                "OR (status = 'failed' "
                "AND completed_at IS NOT NULL "
                "AND failure_message IS NOT NULL)"
            ),
            name="ck_recovery_agent_runs_lifecycle",
        ),
        Index(
            "ix_recovery_agent_runs_case_started",
            "recovery_case_id",
            "started_at",
        ),
        Index(
            "ix_recovery_agent_runs_status_started",
            "status",
            "started_at",
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
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RecoveryAgentRunStatus.STARTED.value,
        server_default=RecoveryAgentRunStatus.STARTED.value,
    )
    planner_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    model_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    prompt_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    input_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    reasoning_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    proposed_action_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    input_token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    output_token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    failure_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RecoveryAction(Base):
    """Policy-evaluated recovery proposal and its execution projection."""

    __tablename__ = "recovery_actions"
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "sequence_number",
            name="uq_recovery_actions_run_sequence",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_recovery_actions_idempotency_key",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_recovery_actions_sequence",
        ),
        CheckConstraint(
            (
                "action_type IN "
                "('create_payment_link', 'send_recovery_message', "
                "'offer_alternate_method', 'wait', "
                "'escalate_human', 'stop_recovery')"
            ),
            name="ck_recovery_actions_type",
        ),
        CheckConstraint(
            (
                "status IN "
                "('allowed', 'blocked', 'escalated', 'stopped', "
                "'scheduled', 'executing', 'succeeded', "
                "'failed', 'cancelled')"
            ),
            name="ck_recovery_actions_status",
        ),
        CheckConstraint(
            "policy_outcome IN ('allow', 'block', 'escalate', 'stop')",
            name="ck_recovery_actions_policy_outcome",
        ),
        CheckConstraint(
            "amount_minor IS NULL OR amount_minor > 0",
            name="ck_recovery_actions_amount",
        ),
        CheckConstraint(
            "execution_attempt_count >= 0",
            name="ck_recovery_actions_attempt_count",
        ),
        CheckConstraint(
            (
                "(action_type = 'create_payment_link' "
                "AND amount_minor IS NOT NULL "
                "AND currency IS NOT NULL) "
                "OR action_type <> 'create_payment_link'"
            ),
            name="ck_recovery_actions_payment_link_shape",
        ),
        CheckConstraint(
            (
                "(action_type IN "
                "('send_recovery_message', 'offer_alternate_method') "
                "AND channel IS NOT NULL) "
                "OR action_type NOT IN "
                "('send_recovery_message', 'offer_alternate_method')"
            ),
            name="ck_recovery_actions_contact_shape",
        ),
        CheckConstraint(
            ("(action_type = 'wait' AND execute_after IS NOT NULL) OR action_type <> 'wait'"),
            name="ck_recovery_actions_wait_shape",
        ),
        CheckConstraint(
            (
                "(policy_outcome = 'allow' "
                "AND jsonb_array_length(policy_guardrails) = 0) "
                "OR (policy_outcome <> 'allow' "
                "AND jsonb_array_length(policy_guardrails) >= 1)"
            ),
            name="ck_recovery_actions_policy_evidence",
        ),
        CheckConstraint(
            (
                "(policy_outcome = 'block' AND status = 'blocked') "
                "OR (policy_outcome = 'escalate' "
                "AND status = 'escalated') "
                "OR (policy_outcome = 'stop' AND status = 'stopped') "
                "OR (policy_outcome = 'allow' "
                "AND status IN "
                "('allowed', 'scheduled', 'executing', "
                "'succeeded', 'failed', 'cancelled'))"
            ),
            name="ck_recovery_actions_policy_status",
        ),
        CheckConstraint(
            (
                "(status = 'succeeded' AND completed_at IS NOT NULL) "
                "OR (status = 'failed' "
                "AND completed_at IS NOT NULL "
                "AND last_error IS NOT NULL) "
                "OR status NOT IN ('succeeded', 'failed')"
            ),
            name="ck_recovery_actions_completion",
        ),
        Index(
            "ix_recovery_actions_execution_queue",
            "status",
            "execute_after",
            "created_at",
        ),
        Index(
            "ix_recovery_actions_case_created",
            "recovery_case_id",
            "created_at",
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
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_agent_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    action_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    proposal_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    amount_minor: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
    )
    channel: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    target_payment_method: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    execute_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    policy_outcome: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    policy_guardrails: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    policy_explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    policy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="deterministic-v1",
        server_default="deterministic-v1",
    )
    policy_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    execution_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    provider_action_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    provider_action_status: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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


class RecoveryAuditEvent(Base):
    """Append-only, hash-chain-ready audit event for recovery decisions."""

    __tablename__ = "recovery_audit_events"
    __table_args__ = (
        UniqueConstraint(
            "event_hash",
            name="uq_recovery_audit_events_hash",
        ),
        CheckConstraint(
            ("actor_type IN ('system', 'agent', 'policy', 'worker', 'operator', 'razorpay')"),
            name="ck_recovery_audit_events_actor",
        ),
        CheckConstraint(
            "char_length(event_hash) = 64",
            name="ck_recovery_audit_events_hash_length",
        ),
        CheckConstraint(
            ("previous_event_hash IS NULL OR char_length(previous_event_hash) = 64"),
            name="ck_recovery_audit_events_previous_hash_length",
        ),
        Index(
            "ix_recovery_audit_events_case_occurred",
            "recovery_case_id",
            "occurred_at",
        ),
        Index(
            "ix_recovery_audit_events_action_occurred",
            "recovery_action_id",
            "occurred_at",
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
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_agent_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    recovery_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "recovery_actions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    event_data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    previous_event_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    event_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    hash_algorithm: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="sha256",
        server_default="sha256",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
