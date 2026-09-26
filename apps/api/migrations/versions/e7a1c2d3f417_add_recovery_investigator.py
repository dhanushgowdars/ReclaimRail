"""add durable recovery investigator transcript

Revision ID: e7a1c2d3f417
Revises: d3e6a9b4c201
Create Date: 2026-09-25 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7a1c2d3f417"
down_revision: str | Sequence[str] | None = "d3e6a9b4c201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_investigation_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=False),
        sa.Column("payment_attempt_id", sa.UUID(), nullable=False),
        sa.Column("truth_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("truth_version", sa.Integer(), nullable=False),
        sa.Column("evidence_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), server_default="running", nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("model_version", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("tool_registry_version", sa.String(64), nullable=False),
        sa.Column("shadow_mode", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("max_model_retries", sa.Integer(), nullable=False),
        sa.Column("max_total_tokens", sa.Integer(), nullable=False),
        sa.Column("max_duration_ms", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("terminal_reason", sa.String(128), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column(
            "result_evidence_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('running','completed','abstained','fallback','failed_safe')",
            name="ck_investigation_session_status",
        ),
        sa.CheckConstraint("case_version >= 0", name="ck_investigation_case_version"),
        sa.CheckConstraint("truth_version >= 1", name="ck_investigation_truth_version"),
        sa.CheckConstraint("max_tool_calls >= 1", name="ck_investigation_tool_budget"),
        sa.CheckConstraint("max_model_retries >= 0", name="ck_investigation_retry_budget"),
        sa.CheckConstraint("max_total_tokens >= 256", name="ck_investigation_token_budget"),
        sa.CheckConstraint("max_duration_ms >= 1000", name="ck_investigation_duration_budget"),
        sa.CheckConstraint("tool_call_count >= 0", name="ck_investigation_tool_count"),
        sa.ForeignKeyConstraint(["recovery_case_id"], ["recovery_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"], ["payment_attempts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["truth_snapshot_id"], ["payment_truth_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recovery_case_id", "case_version", name="uq_investigation_case_version"
        ),
    )
    op.create_index(
        "ix_investigation_case_started",
        "recovery_investigation_sessions",
        ["recovery_case_id", "started_at"],
    )
    op.create_index(
        "ix_investigation_status_started",
        "recovery_investigation_sessions",
        ["status", "started_at"],
    )
    op.create_table(
        "recovery_investigation_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column(
            "evidence_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("model_response_digest", sa.String(64), nullable=False),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("cumulative_tool_calls", sa.Integer(), nullable=False),
        sa.Column("cumulative_total_tokens", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence_number >= 1", name="ck_investigation_step_sequence"),
        sa.CheckConstraint(
            "outcome IN ('succeeded','unavailable','rejected','failed')",
            name="ck_investigation_step_outcome",
        ),
        sa.CheckConstraint("cumulative_tool_calls >= 1", name="ck_investigation_step_tool_count"),
        sa.CheckConstraint("cumulative_total_tokens >= 0", name="ck_investigation_step_tokens"),
        sa.CheckConstraint("elapsed_ms >= 0", name="ck_investigation_step_elapsed"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["recovery_investigation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_investigation_step_sequence"),
    )
    op.create_index(
        "ix_investigation_steps_session_sequence",
        "recovery_investigation_steps",
        ["session_id", "sequence_number"],
    )
    op.create_table(
        "recovery_investigation_hypotheses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("hypothesis_key", sa.String(80), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "supporting_evidence_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "contradicting_evidence_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_questions",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("next_observation", sa.Text(), nullable=True),
        sa.Column("first_step", sa.Integer(), nullable=False),
        sa.Column("last_step", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('open','supported','contradicted','unresolved','rejected')",
            name="ck_investigation_hypothesis_status",
        ),
        sa.CheckConstraint("first_step >= 0", name="ck_investigation_hypothesis_first_step"),
        sa.CheckConstraint("last_step >= first_step", name="ck_investigation_hypothesis_last_step"),
        sa.CheckConstraint("version >= 1", name="ck_investigation_hypothesis_version"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["recovery_investigation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "hypothesis_key", name="uq_investigation_hypothesis_key"),
    )


def downgrade() -> None:
    op.drop_table("recovery_investigation_hypotheses")
    op.drop_index(
        "ix_investigation_steps_session_sequence", table_name="recovery_investigation_steps"
    )
    op.drop_table("recovery_investigation_steps")
    op.drop_index("ix_investigation_status_started", table_name="recovery_investigation_sessions")
    op.drop_index("ix_investigation_case_started", table_name="recovery_investigation_sessions")
    op.drop_table("recovery_investigation_sessions")
