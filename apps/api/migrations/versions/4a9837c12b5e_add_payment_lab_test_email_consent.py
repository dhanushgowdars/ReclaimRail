"""add payment lab test email consent

Revision ID: 4a9837c12b5e
Revises: f2a4c91d73e1
Create Date: 2026-08-29 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a9837c12b5e"
down_revision: str | Sequence[str] | None = "f2a4c91d73e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_lab_runs",
        sa.Column(
            "test_email_contact_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_lab_runs", "test_email_contact_consent")
