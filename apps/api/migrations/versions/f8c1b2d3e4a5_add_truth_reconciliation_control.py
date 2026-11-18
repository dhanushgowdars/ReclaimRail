"""add durable payment truth reconciliation control

Revision ID: f8c1b2d3e4a5
Revises: e7a1c2d3f417
Create Date: 2026-11-17 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8c1b2d3e4a5"
down_revision: str | Sequence[str] | None = "e7a1c2d3f417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_truth_reconciliation_state",
        sa.Column("payment_attempt_id", sa.UUID(), nullable=False),
        sa.Column("payment_state_version", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("observation_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("circuit_open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exhausted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "payment_state_version >= 0",
            name="ck_truth_reconciliation_payment_state_version",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_truth_reconciliation_attempt_count",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_truth_reconciliation_consecutive_failures",
        ),
        sa.CheckConstraint(
            "observation_sequence >= 0",
            name="ck_truth_reconciliation_observation_sequence",
        ),
        sa.CheckConstraint(
            (
                "blocked_reason IS NULL OR "
                "blocked_reason IN ('controlled_synthetic', 'retry_budget_exhausted')"
            ),
            name="ck_truth_reconciliation_blocked_reason",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("payment_attempt_id"),
    )
    op.create_index(
        "ix_truth_reconciliation_retry",
        "payment_truth_reconciliation_state",
        ["next_retry_at", "circuit_open_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_truth_reconciliation_retry",
        table_name="payment_truth_reconciliation_state",
    )
    op.drop_table("payment_truth_reconciliation_state")
