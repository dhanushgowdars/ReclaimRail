"""add controlled evaluation persistence

Revision ID: f913b7d0e101
Revises: ebd83b805c6c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f913b7d0e101"
down_revision: str | Sequence[str] | None = "ebd83b805c6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("scenario_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("audit_root_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provenance = 'controlled_synthetic'", name="ck_evaluation_runs_provenance"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_evaluation_runs_run_key"),
    )
    op.create_table(
        "evaluation_scenarios",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("evaluation_run_id", sa.UUID(), nullable=False),
        sa.Column("scenario_number", sa.Integer(), nullable=False),
        sa.Column("scenario_key", sa.String(length=64), nullable=False),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("original_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("at_risk", sa.Boolean(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("attempted", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("policy_outcome", sa.String(length=16), nullable=False),
        sa.Column("guardrails", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recovered_minor", sa.BigInteger(), nullable=False),
        sa.Column("control_recovered_minor", sa.BigInteger(), nullable=False),
        sa.Column("pending_minor", sa.BigInteger(), nullable=False),
        sa.Column("protected_minor", sa.BigInteger(), nullable=False),
        sa.Column("decision_latency_ms", sa.Integer(), nullable=False),
        sa.Column("audit_previous_hash", sa.String(length=64), nullable=True),
        sa.Column("audit_event_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scenario_number >= 1", name="ck_evaluation_scenarios_number"),
        sa.CheckConstraint("original_amount_minor > 0", name="ck_evaluation_scenarios_amount"),
        sa.CheckConstraint("recovered_minor >= 0", name="ck_evaluation_scenarios_recovered"),
        sa.CheckConstraint("pending_minor >= 0", name="ck_evaluation_scenarios_pending"),
        sa.CheckConstraint("protected_minor >= 0", name="ck_evaluation_scenarios_protected"),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id", "scenario_number", name="uq_evaluation_scenarios_run_number"
        ),
    )
    op.create_index(
        "ix_evaluation_scenarios_run_outcome",
        "evaluation_scenarios",
        ["evaluation_run_id", "outcome"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_scenarios_run_outcome", table_name="evaluation_scenarios")
    op.drop_table("evaluation_scenarios")
    op.drop_table("evaluation_runs")
