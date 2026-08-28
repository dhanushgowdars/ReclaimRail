"""expand recovery approval risk context

Revision ID: f2a4c91d73e1
Revises: c4b8f1a29d60
Create Date: 2026-08-28 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a4c91d73e1"
down_revision: str | Sequence[str] | None = "c4b8f1a29d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_recovery_approvals_threshold_met",
        "recovery_approvals",
        type_="check",
    )
    op.drop_constraint(
        "ck_recovery_approvals_threshold",
        "recovery_approvals",
        type_="check",
    )
    op.alter_column(
        "recovery_approvals",
        "threshold_minor",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_recovery_approvals_threshold",
        "recovery_approvals",
        "threshold_minor IS NULL OR threshold_minor > 0",
    )
    op.create_check_constraint(
        "ck_recovery_approvals_threshold_met",
        "recovery_approvals",
        "threshold_minor IS NULL OR amount_minor >= threshold_minor",
    )
    op.add_column(
        "recovery_approvals",
        sa.Column(
            "request_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recovery_approvals", "request_context")
    op.drop_constraint(
        "ck_recovery_approvals_threshold_met",
        "recovery_approvals",
        type_="check",
    )
    op.drop_constraint(
        "ck_recovery_approvals_threshold",
        "recovery_approvals",
        type_="check",
    )
    op.execute(
        "UPDATE recovery_approvals SET threshold_minor = amount_minor WHERE threshold_minor IS NULL"
    )
    op.alter_column(
        "recovery_approvals",
        "threshold_minor",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_recovery_approvals_threshold",
        "recovery_approvals",
        "threshold_minor > 0",
    )
    op.create_check_constraint(
        "ck_recovery_approvals_threshold_met",
        "recovery_approvals",
        "amount_minor >= threshold_minor",
    )
