"""merge phase 13 evaluation lineage

Revision ID: dfaf7934edc7
Revises: 4a9837c12b5e, f913b7d0e101
Create Date: 2026-09-03 16:56:10.892336

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "dfaf7934edc7"
down_revision: str | Sequence[str] | None = ("4a9837c12b5e", "f913b7d0e101")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
