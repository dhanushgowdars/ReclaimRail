"""add payment lab runs

Revision ID: 1db7d19e8a6c
Revises: ebd83b805c6c
Create Date: 2026-08-26 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1db7d19e8a6c"
down_revision: str | Sequence[str] | None = "ebd83b805c6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_lab_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_request_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "provenance",
            sa.String(length=32),
            server_default="razorpay_test",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="creating",
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("receipt", sa.String(length=40), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=True),
        sa.Column("provider_order_status", sa.String(length=32), nullable=True),
        sa.Column(
            "provider_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("payment_attempt_id", sa.UUID(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "checkout_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0",
            name="ck_payment_lab_runs_amount_minor",
        ),
        sa.CheckConstraint(
            "char_length(currency) = 3",
            name="ck_payment_lab_runs_currency",
        ),
        sa.CheckConstraint(
            "mode IN ('guided', 'custom', 'replay')",
            name="ck_payment_lab_runs_mode",
        ),
        sa.CheckConstraint(
            "payment_method IN ('upi', 'card', 'netbanking', 'wallet')",
            name="ck_payment_lab_runs_payment_method",
        ),
        sa.CheckConstraint(
            "provenance IN ('razorpay_test', 'verified_replay')",
            name="ck_payment_lab_runs_provenance",
        ),
        sa.CheckConstraint(
            (
                "(status = 'checkout_ready' AND provider_order_id IS NOT NULL) "
                "OR status <> 'checkout_ready'"
            ),
            name="ck_payment_lab_runs_ready_order",
        ),
        sa.CheckConstraint(
            (
                "status IN ("
                "'creating', 'checkout_ready', 'payment_attempted', "
                "'recovery_running', 'completed', 'provider_failed', 'expired'"
                ")"
            ),
            name="ck_payment_lab_runs_status",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_payment_lab_runs_version",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name=op.f("fk_payment_lab_runs_payment_attempt_id_payment_attempts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_lab_runs")),
        sa.UniqueConstraint(
            "client_request_id",
            name="uq_payment_lab_runs_client_request_id",
        ),
        sa.UniqueConstraint(
            "payment_attempt_id",
            name="uq_payment_lab_runs_payment_attempt_id",
        ),
        sa.UniqueConstraint(
            "provider_order_id",
            name="uq_payment_lab_runs_provider_order_id",
        ),
        sa.UniqueConstraint(
            "receipt",
            name="uq_payment_lab_runs_receipt",
        ),
    )
    op.create_index(
        "ix_payment_lab_runs_provenance_created",
        "payment_lab_runs",
        ["provenance", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_lab_runs_status_created",
        "payment_lab_runs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_lab_runs_status_created",
        table_name="payment_lab_runs",
    )
    op.drop_index(
        "ix_payment_lab_runs_provenance_created",
        table_name="payment_lab_runs",
    )
    op.drop_table("payment_lab_runs")
