"""add recovery action provider evidence

Revision ID: a73d91c4e2f8
Revises: 1db7d19e8a6c
Create Date: 2026-08-27 11:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a73d91c4e2f8"
down_revision: str | Sequence[str] | None = "1db7d19e8a6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recovery_actions",
        sa.Column(
            "provider_action_url",
            sa.String(length=2048),
            nullable=True,
        ),
    )
    op.add_column(
        "recovery_actions",
        sa.Column(
            "provider_action_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "recovery_actions",
        "provider_action_expires_at",
    )
    op.drop_column(
        "recovery_actions",
        "provider_action_url",
    )
