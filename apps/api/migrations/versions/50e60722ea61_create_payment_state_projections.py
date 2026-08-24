"""create payment state projections

Revision ID: 50e60722ea61
Revises: 81959b025796
Create Date: 2026-08-24 15:04:50.810278

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50e60722ea61"
down_revision: str | Sequence[str] | None = "81959b025796"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "payment_attempts",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="razorpay",
            nullable=False,
        ),
        sa.Column(
            "provider_payment_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "provider_order_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "amount_minor",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
        ),
        sa.Column(
            "method",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "current_state",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "state_provider_event_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "state_webhook_event_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "state_event_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "error_code",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "error_description",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "error_source",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "error_step",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "error_reason",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "recovery_eligible",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "recovery_stopped_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "recovery_stop_reason",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "late_authorization_detected_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        sa.CheckConstraint(
            "NOT recovery_eligible OR current_state = 'failed'",
            name="ck_payment_attempts_recovery_eligible",
        ),
        sa.CheckConstraint(
            (
                "current_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_attempts_current_state",
        ),
        sa.CheckConstraint(
            "amount_minor >= 0",
            name="ck_payment_attempts_amount_minor",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_payment_attempts_state_version",
        ),
        sa.ForeignKeyConstraint(
            ["state_webhook_event_id"],
            ["webhook_events.id"],
            name=op.f("fk_payment_attempts_state_webhook_event_id_webhook_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_payment_attempts"),
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_payment_id",
            name="uq_payment_attempts_provider_payment_id",
        ),
    )

    op.create_index(
        op.f("ix_payment_attempts_provider_order_id"),
        "payment_attempts",
        ["provider_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_payment_attempts_recovery_queue",
        "payment_attempts",
        ["recovery_eligible", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_attempts_state_updated",
        "payment_attempts",
        ["current_state", "updated_at"],
        unique=False,
    )

    op.create_table(
        "payment_state_transitions",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "payment_attempt_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "webhook_event_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "provider_event_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "previous_state",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "incoming_state",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "resulting_state",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "resulting_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "late_authorization",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "stop_recovery",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "event_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "incoming_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_state_transitions_incoming_state",
        ),
        sa.CheckConstraint(
            (
                "outcome IN "
                "('applied', 'ignored_duplicate', "
                "'ignored_out_of_order', 'ignored_terminal')"
            ),
            name="ck_payment_state_transitions_outcome",
        ),
        sa.CheckConstraint(
            (
                "previous_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_state_transitions_previous_state",
        ),
        sa.CheckConstraint(
            (
                "resulting_state IN "
                "('unknown', 'created', 'failed', 'authorized', "
                "'captured', 'refunded')"
            ),
            name="ck_payment_state_transitions_resulting_state",
        ),
        sa.CheckConstraint(
            "resulting_version >= 0",
            name="ck_payment_state_transitions_resulting_version",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name=op.f("fk_payment_state_transitions_payment_attempt_id_payment_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"],
            ["webhook_events.id"],
            name=op.f("fk_payment_state_transitions_webhook_event_id_webhook_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_payment_state_transitions"),
        ),
        sa.UniqueConstraint(
            "webhook_event_id",
            name="uq_payment_state_transitions_webhook_event_id",
        ),
    )

    op.create_index(
        "ix_payment_state_transitions_attempt_processed",
        "payment_state_transitions",
        ["payment_attempt_id", "processed_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_state_transitions_outcome_processed",
        "payment_state_transitions",
        ["outcome", "processed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_state_transitions_payment_attempt_id"),
        "payment_state_transitions",
        ["payment_attempt_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_payment_state_transitions_payment_attempt_id"),
        table_name="payment_state_transitions",
    )
    op.drop_index(
        "ix_payment_state_transitions_outcome_processed",
        table_name="payment_state_transitions",
    )
    op.drop_index(
        "ix_payment_state_transitions_attempt_processed",
        table_name="payment_state_transitions",
    )
    op.drop_table("payment_state_transitions")

    op.drop_index(
        "ix_payment_attempts_state_updated",
        table_name="payment_attempts",
    )
    op.drop_index(
        "ix_payment_attempts_recovery_queue",
        table_name="payment_attempts",
    )
    op.drop_index(
        op.f("ix_payment_attempts_provider_order_id"),
        table_name="payment_attempts",
    )
    op.drop_table("payment_attempts")
