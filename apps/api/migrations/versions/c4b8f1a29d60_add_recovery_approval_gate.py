"""add recovery approval gate

Revision ID: c4b8f1a29d60
Revises: a73d91c4e2f8
Create Date: 2026-08-28 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4b8f1a29d60"
down_revision: str | Sequence[str] | None = "a73d91c4e2f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "recovery_cases",
        "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "recovery_actions",
        "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.drop_constraint(
        "ck_recovery_cases_status",
        "recovery_cases",
        type_="check",
    )
    op.drop_constraint(
        "ck_recovery_cases_lifecycle",
        "recovery_cases",
        type_="check",
    )
    op.create_check_constraint(
        "ck_recovery_cases_status",
        "recovery_cases",
        (
            "status IN ('open', 'planning', 'ready', 'awaiting_approval', "
            "'executing', 'waiting', 'recovered', 'exhausted', "
            "'cancelled', 'escalated')"
        ),
    )
    op.create_check_constraint(
        "ck_recovery_cases_lifecycle",
        "recovery_cases",
        (
            "(status = 'recovered' AND recovered_at IS NOT NULL "
            "AND closed_at IS NOT NULL) "
            "OR (status IN ('exhausted', 'cancelled') "
            "AND recovered_at IS NULL AND closed_at IS NOT NULL) "
            "OR (status IN ('open', 'planning', 'ready', "
            "'awaiting_approval', 'executing', 'waiting', 'escalated') "
            "AND recovered_at IS NULL AND closed_at IS NULL)"
        ),
    )

    op.drop_constraint(
        "ck_recovery_actions_status",
        "recovery_actions",
        type_="check",
    )
    op.drop_constraint(
        "ck_recovery_actions_policy_status",
        "recovery_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_recovery_actions_status",
        "recovery_actions",
        (
            "status IN ('allowed', 'approval_required', 'blocked', "
            "'escalated', 'stopped', 'scheduled', 'executing', "
            "'succeeded', 'failed', 'cancelled')"
        ),
    )
    op.create_check_constraint(
        "ck_recovery_actions_policy_status",
        "recovery_actions",
        (
            "(policy_outcome = 'block' AND status = 'blocked') "
            "OR (policy_outcome = 'escalate' AND status = 'escalated') "
            "OR (policy_outcome = 'stop' AND status = 'stopped') "
            "OR (policy_outcome = 'allow' AND status IN "
            "('allowed', 'approval_required', 'scheduled', 'executing', "
            "'succeeded', 'failed', 'cancelled'))"
        ),
    )

    op.create_table(
        "recovery_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=False),
        sa.Column("recovery_action_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("request_reason", sa.String(length=128), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("threshold_minor", sa.BigInteger(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
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
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_recovery_approvals_status",
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_recovery_approvals_amount"),
        sa.CheckConstraint(
            "threshold_minor > 0",
            name="ck_recovery_approvals_threshold",
        ),
        sa.CheckConstraint(
            "amount_minor >= threshold_minor",
            name="ck_recovery_approvals_threshold_met",
        ),
        sa.CheckConstraint(
            "expires_at > requested_at",
            name="ck_recovery_approvals_expiry",
        ),
        sa.CheckConstraint("version >= 0", name="ck_recovery_approvals_version"),
        sa.CheckConstraint(
            (
                "(status = 'pending' AND decided_at IS NULL "
                "AND decided_by IS NULL AND decision_reason IS NULL) "
                "OR (status IN ('approved', 'rejected') "
                "AND decided_at IS NOT NULL AND decided_by IS NOT NULL "
                "AND decision_reason IS NOT NULL) "
                "OR (status = 'expired' AND decided_at IS NOT NULL "
                "AND decided_by IS NULL AND decision_reason IS NOT NULL)"
            ),
            name="ck_recovery_approvals_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f("fk_recovery_approvals_recovery_case_id_recovery_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_action_id"],
            ["recovery_actions.id"],
            name=op.f("fk_recovery_approvals_recovery_action_id_recovery_actions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_approvals")),
        sa.UniqueConstraint(
            "recovery_action_id",
            name="uq_recovery_approvals_action",
        ),
    )
    op.create_index(
        "ix_recovery_approvals_queue",
        "recovery_approvals",
        ["status", "expires_at", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_approvals_case_requested",
        "recovery_approvals",
        ["recovery_case_id", "requested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recovery_approvals_case_requested",
        table_name="recovery_approvals",
    )
    op.drop_index(
        "ix_recovery_approvals_queue",
        table_name="recovery_approvals",
    )
    op.drop_table("recovery_approvals")

    op.execute(
        "UPDATE recovery_cases SET status = 'escalated', next_action_at = NULL "
        "WHERE status = 'awaiting_approval'",
    )
    op.execute(
        "UPDATE recovery_actions SET status = 'cancelled' WHERE status = 'approval_required'",
    )

    op.drop_constraint(
        "ck_recovery_actions_policy_status",
        "recovery_actions",
        type_="check",
    )
    op.drop_constraint(
        "ck_recovery_actions_status",
        "recovery_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_recovery_actions_status",
        "recovery_actions",
        (
            "status IN ('allowed', 'blocked', 'escalated', 'stopped', "
            "'scheduled', 'executing', 'succeeded', 'failed', 'cancelled')"
        ),
    )

    op.alter_column(
        "recovery_actions",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_recovery_actions_policy_status",
        "recovery_actions",
        (
            "(policy_outcome = 'block' AND status = 'blocked') "
            "OR (policy_outcome = 'escalate' AND status = 'escalated') "
            "OR (policy_outcome = 'stop' AND status = 'stopped') "
            "OR (policy_outcome = 'allow' AND status IN "
            "('allowed', 'scheduled', 'executing', 'succeeded', "
            "'failed', 'cancelled'))"
        ),
    )

    op.alter_column(
        "recovery_cases",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )

    op.drop_constraint(
        "ck_recovery_cases_lifecycle",
        "recovery_cases",
        type_="check",
    )
    op.drop_constraint(
        "ck_recovery_cases_status",
        "recovery_cases",
        type_="check",
    )
    op.create_check_constraint(
        "ck_recovery_cases_status",
        "recovery_cases",
        (
            "status IN ('open', 'planning', 'ready', 'executing', "
            "'waiting', 'recovered', 'exhausted', 'cancelled', 'escalated')"
        ),
    )
    op.create_check_constraint(
        "ck_recovery_cases_lifecycle",
        "recovery_cases",
        (
            "(status = 'recovered' AND recovered_at IS NOT NULL "
            "AND closed_at IS NOT NULL) "
            "OR (status IN ('exhausted', 'cancelled') "
            "AND recovered_at IS NULL AND closed_at IS NOT NULL) "
            "OR (status IN ('open', 'planning', 'ready', 'executing', "
            "'waiting', 'escalated') AND recovered_at IS NULL "
            "AND closed_at IS NULL)"
        ),
    )
