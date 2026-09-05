"""add provider verification metadata to payment lab runs

Revision ID: 9fd5e3ab10f1
Revises: a4c98e731d21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9fd5e3ab10f1"
down_revision: str | Sequence[str] | None = "a4c98e731d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_lab_runs",
        sa.Column("provider_evidence_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "payment_lab_runs",
        sa.Column("provider_evidence_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_lab_runs", "provider_evidence_checked_at")
    op.drop_column("payment_lab_runs", "provider_evidence_source")
