"""add sanitized investigator provider attempts

Revision ID: b17b9c3d4e5f
Revises: f8c1b2d3e4a5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b17b9c3d4e5f"
down_revision: str | Sequence[str] | None = "f8c1b2d3e4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_investigation_provider_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("requested_model", sa.String(128), nullable=False),
        sa.Column("returned_model", sa.String(128), nullable=True),
        sa.Column("model_version", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_kind", sa.String(64), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("input_token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("selected_result", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint(
            "sequence_number >= 1", name="ck_investigation_provider_attempt_sequence"
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_investigation_provider_attempt_latency"),
        sa.CheckConstraint(
            "input_token_count >= 0", name="ck_investigation_provider_attempt_input_tokens"
        ),
        sa.CheckConstraint(
            "output_token_count >= 0", name="ck_investigation_provider_attempt_output_tokens"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["recovery_investigation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "sequence_number", name="uq_investigation_provider_attempt"
        ),
    )


def downgrade() -> None:
    op.drop_table("recovery_investigation_provider_attempts")
