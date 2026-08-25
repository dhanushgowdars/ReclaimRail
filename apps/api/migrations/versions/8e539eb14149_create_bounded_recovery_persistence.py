"""create bounded recovery persistence

Revision ID: 8e539eb14149
Revises: bc977924af18
Create Date: 2026-08-24 22:08:25.735107

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8e539eb14149"
down_revision: str | Sequence[str] | None = "bc977924af18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recovery_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_attempt_id", sa.UUID(), nullable=False),
        sa.Column("source_incident_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="open",
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_method", sa.String(length=64), nullable=True),
        sa.Column(
            "recovery_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "customer_contact_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "active_payment_link_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "last_customer_contact_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "next_action_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "late_authorization_detected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "recovered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "close_reason",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            (
                "status IN "
                "('open', 'planning', 'ready', 'executing', "
                "'waiting', 'recovered', 'exhausted', "
                "'cancelled', 'escalated')"
            ),
            name="ck_recovery_cases_status",
        ),
        sa.CheckConstraint(
            "amount_minor > 0",
            name="ck_recovery_cases_amount_minor",
        ),
        sa.CheckConstraint(
            "recovery_attempt_count >= 0",
            name="ck_recovery_cases_attempt_count",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_recovery_cases_version",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name=op.f(
                "fk_recovery_cases_payment_attempt_id_payment_attempts",
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_incident_id"],
            ["revenue_incidents.id"],
            name=op.f(
                "fk_recovery_cases_source_incident_id_revenue_incidents",
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_recovery_cases"),
        ),
        sa.UniqueConstraint(
            "payment_attempt_id",
            name="uq_recovery_cases_payment_attempt_id",
        ),
    )
    op.create_index(
        "ix_recovery_cases_incident_status",
        "recovery_cases",
        ["source_incident_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_cases_work_queue",
        "recovery_cases",
        ["status", "next_action_at", "updated_at"],
        unique=False,
    )

    op.create_table(
        "recovery_agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="started",
            nullable=False,
        ),
        sa.Column(
            "planner_provider",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "model_name",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "prompt_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "proposed_action_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "planner_provider IN ('deterministic', 'gemini')",
            name="ck_recovery_agent_runs_provider",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'superseded')",
            name="ck_recovery_agent_runs_status",
        ),
        sa.CheckConstraint(
            "input_token_count IS NULL OR input_token_count >= 0",
            name="ck_recovery_agent_runs_input_tokens",
        ),
        sa.CheckConstraint(
            "output_token_count IS NULL OR output_token_count >= 0",
            name="ck_recovery_agent_runs_output_tokens",
        ),
        sa.CheckConstraint(
            "proposed_action_count >= 0",
            name="ck_recovery_agent_runs_action_count",
        ),
        sa.CheckConstraint(
            "run_number >= 1",
            name="ck_recovery_agent_runs_number",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f(
                "fk_recovery_agent_runs_recovery_case_id_recovery_cases",
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_recovery_agent_runs"),
        ),
        sa.UniqueConstraint(
            "recovery_case_id",
            "run_number",
            name="uq_recovery_agent_runs_case_number",
        ),
    )
    op.create_index(
        "ix_recovery_agent_runs_case_started",
        "recovery_agent_runs",
        ["recovery_case_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_agent_runs_status_started",
        "recovery_agent_runs",
        ["status", "started_at"],
        unique=False,
    )

    op.create_table(
        "recovery_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("proposal_reason", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=True),
        sa.Column(
            "target_payment_method",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "execute_after",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "policy_outcome",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "policy_guardrails",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("policy_explanation", sa.Text(), nullable=False),
        sa.Column(
            "policy_version",
            sa.String(length=32),
            server_default="deterministic-v1",
            nullable=False,
        ),
        sa.Column(
            "policy_evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "execution_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "provider_action_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "provider_action_status",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "(action_type = 'create_payment_link' "
                "AND amount_minor IS NOT NULL "
                "AND currency IS NOT NULL) "
                "OR action_type <> 'create_payment_link'"
            ),
            name="ck_recovery_actions_payment_link_shape",
        ),
        sa.CheckConstraint(
            ("(action_type = 'wait' AND execute_after IS NOT NULL) OR action_type <> 'wait'"),
            name="ck_recovery_actions_wait_shape",
        ),
        sa.CheckConstraint(
            (
                "(action_type IN "
                "('send_recovery_message', 'offer_alternate_method') "
                "AND channel IS NOT NULL) "
                "OR action_type NOT IN "
                "('send_recovery_message', 'offer_alternate_method')"
            ),
            name="ck_recovery_actions_contact_shape",
        ),
        sa.CheckConstraint(
            (
                "(policy_outcome = 'allow' "
                "AND jsonb_array_length(policy_guardrails) = 0) "
                "OR (policy_outcome <> 'allow' "
                "AND jsonb_array_length(policy_guardrails) >= 1)"
            ),
            name="ck_recovery_actions_policy_evidence",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            (
                "(status = 'succeeded' "
                "AND completed_at IS NOT NULL) "
                "OR (status = 'failed' "
                "AND completed_at IS NOT NULL "
                "AND last_error IS NOT NULL) "
                "OR status NOT IN ('succeeded', 'failed')"
            ),
            name="ck_recovery_actions_completion",
        ),
        sa.CheckConstraint(
            (
                "action_type IN "
                "('create_payment_link', 'send_recovery_message', "
                "'offer_alternate_method', 'wait', "
                "'escalate_human', 'stop_recovery')"
            ),
            name="ck_recovery_actions_type",
        ),
        sa.CheckConstraint(
            "policy_outcome IN ('allow', 'block', 'escalate', 'stop')",
            name="ck_recovery_actions_policy_outcome",
        ),
        sa.CheckConstraint(
            (
                "status IN "
                "('allowed', 'blocked', 'escalated', 'stopped', "
                "'scheduled', 'executing', 'succeeded', "
                "'failed', 'cancelled')"
            ),
            name="ck_recovery_actions_status",
        ),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor > 0",
            name="ck_recovery_actions_amount",
        ),
        sa.CheckConstraint(
            "execution_attempt_count >= 0",
            name="ck_recovery_actions_attempt_count",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_recovery_actions_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["recovery_agent_runs.id"],
            name=op.f(
                "fk_recovery_actions_agent_run_id_recovery_agent_runs",
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f(
                "fk_recovery_actions_recovery_case_id_recovery_cases",
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_recovery_actions"),
        ),
        sa.UniqueConstraint(
            "agent_run_id",
            "sequence_number",
            name="uq_recovery_actions_run_sequence",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_recovery_actions_idempotency_key",
        ),
    )
    op.create_index(
        "ix_recovery_actions_case_created",
        "recovery_actions",
        ["recovery_case_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_actions_execution_queue",
        "recovery_actions",
        ["status", "execute_after", "created_at"],
        unique=False,
    )

    op.create_table(
        "recovery_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("recovery_action_id", sa.UUID(), nullable=True),
        sa.Column(
            "event_type",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "event_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "previous_event_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "event_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "hash_algorithm",
            sa.String(length=16),
            server_default="sha256",
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            ("actor_type IN ('system', 'agent', 'policy', 'worker', 'operator', 'razorpay')"),
            name="ck_recovery_audit_events_actor",
        ),
        sa.CheckConstraint(
            "char_length(event_hash) = 64",
            name="ck_recovery_audit_events_hash_length",
        ),
        sa.CheckConstraint(
            ("previous_event_hash IS NULL OR char_length(previous_event_hash) = 64"),
            name="ck_recovery_audit_events_previous_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["recovery_agent_runs.id"],
            name=op.f(
                "fk_recovery_audit_events_agent_run_id_recovery_agent_runs",
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_action_id"],
            ["recovery_actions.id"],
            name=op.f(
                "fk_recovery_audit_events_recovery_action_id_recovery_actions",
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f(
                "fk_recovery_audit_events_recovery_case_id_recovery_cases",
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_recovery_audit_events"),
        ),
        sa.UniqueConstraint(
            "event_hash",
            name="uq_recovery_audit_events_hash",
        ),
    )
    op.create_index(
        "ix_recovery_audit_events_action_occurred",
        "recovery_audit_events",
        ["recovery_action_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_audit_events_case_occurred",
        "recovery_audit_events",
        ["recovery_case_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_recovery_audit_events_case_occurred",
        table_name="recovery_audit_events",
    )
    op.drop_index(
        "ix_recovery_audit_events_action_occurred",
        table_name="recovery_audit_events",
    )
    op.drop_table("recovery_audit_events")

    op.drop_index(
        "ix_recovery_actions_execution_queue",
        table_name="recovery_actions",
    )
    op.drop_index(
        "ix_recovery_actions_case_created",
        table_name="recovery_actions",
    )
    op.drop_table("recovery_actions")

    op.drop_index(
        "ix_recovery_agent_runs_status_started",
        table_name="recovery_agent_runs",
    )
    op.drop_index(
        "ix_recovery_agent_runs_case_started",
        table_name="recovery_agent_runs",
    )
    op.drop_table("recovery_agent_runs")

    op.drop_index(
        "ix_recovery_cases_work_queue",
        table_name="recovery_cases",
    )
    op.drop_index(
        "ix_recovery_cases_incident_status",
        table_name="recovery_cases",
    )
    op.drop_table("recovery_cases")
