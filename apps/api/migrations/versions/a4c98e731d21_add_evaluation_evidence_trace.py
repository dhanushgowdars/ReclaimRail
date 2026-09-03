"""add persisted evidence trace to controlled evaluation scenarios

Revision ID: a4c98e731d21
Revises: dfaf7934edc7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c98e731d21"
down_revision: str | Sequence[str] | None = "dfaf7934edc7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_scenarios",
        sa.Column("observed_condition", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "evaluation_scenarios",
        sa.Column("agent_recommendation", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "evaluation_scenarios", sa.Column("proposed_action", sa.String(length=48), nullable=True)
    )
    op.add_column(
        "evaluation_scenarios",
        sa.Column("expected_policy_outcome", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "evaluation_scenarios",
        sa.Column("policy_explanation", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "evaluation_scenarios", sa.Column("execution_status", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("evaluation_scenarios", "execution_status")
    op.drop_column("evaluation_scenarios", "policy_explanation")
    op.drop_column("evaluation_scenarios", "expected_policy_outcome")
    op.drop_column("evaluation_scenarios", "proposed_action")
    op.drop_column("evaluation_scenarios", "agent_recommendation")
    op.drop_column("evaluation_scenarios", "observed_condition")
