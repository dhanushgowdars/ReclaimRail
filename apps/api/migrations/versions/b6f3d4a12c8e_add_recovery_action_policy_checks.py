"""persist deterministic recovery policy check evidence

Revision ID: b6f3d4a12c8e
Revises: 9fd5e3ab10f1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6f3d4a12c8e"
down_revision: str | Sequence[str] | None = "9fd5e3ab10f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recovery_actions",
        sa.Column(
            "policy_check_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recovery_actions", "policy_check_results")
