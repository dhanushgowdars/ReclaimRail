"""add payment event reliability metadata

Revision ID: d3e6a9b4c201
Revises: 7c2f4a8d19e5
Create Date: 2026-09-22 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e6a9b4c201"
down_revision: str | Sequence[str] | None = "7c2f4a8d19e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_event_replay_audits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_stream", sa.String(length=255), nullable=False),
        sa.Column("source_message_id", sa.String(length=64), nullable=False),
        sa.Column("target_stream", sa.String(length=255), nullable=False),
        sa.Column("target_message_id", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_event_replay_audits")),
        sa.UniqueConstraint(
            "source_stream",
            "source_message_id",
            name="uq_payment_event_replay_source",
        ),
    )
    op.drop_constraint("ck_payment_evidence_source", "payment_evidence", type_="check")
    op.create_check_constraint(
        "ck_payment_evidence_source",
        "payment_evidence",
        (
            "source IN ('provider_payment_api', 'provider_order_api', "
            "'verified_webhook', 'merchant_database', 'recovery_state', "
            "'reconciliation', 'payment_lab', 'recovery_link')"
        ),
    )
    op.add_column("payment_evidence", sa.Column("signature_verified", sa.Boolean(), nullable=True))
    op.add_column(
        "payment_evidence",
        sa.Column(
            "normalized_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "payment_evidence",
        sa.Column(
            "reliability",
            sa.String(length=32),
            server_default="corroborating",
            nullable=False,
        ),
    )
    op.add_column(
        "payment_evidence",
        sa.Column("unavailable_reason", sa.String(length=128), nullable=True),
    )
    op.create_check_constraint(
        "ck_payment_evidence_reliability",
        "payment_evidence",
        "reliability IN ('authoritative', 'corroborating', 'weak')",
    )
    op.add_column(
        "payment_state_transitions",
        sa.Column(
            "evidence_source",
            sa.String(length=32),
            server_default="verified_webhook",
            nullable=False,
        ),
    )
    op.add_column(
        "payment_state_transitions",
        sa.Column(
            "delivery_classification",
            sa.String(length=32),
            server_default="on_time",
            nullable=False,
        ),
    )
    op.add_column(
        "payment_state_transitions",
        sa.Column(
            "delivery_latency_ms",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE payment_state_transitions
        SET
            evidence_source = CASE
                WHEN provider_event_id LIKE 'provider-api:%'
                    THEN 'provider_payment_api'
                ELSE 'verified_webhook'
            END,
            delivery_classification = CASE
                WHEN reason IN ('regression_blocked', 'terminal_state')
                    THEN 'reordered'
                WHEN provider_event_id LIKE 'provider-api:%'
                    THEN 'provider_reconciled'
                WHEN processed_at > event_created_at + INTERVAL '2 minutes'
                    THEN 'delayed'
                ELSE 'on_time'
            END,
            delivery_latency_ms = GREATEST(
                FLOOR(EXTRACT(EPOCH FROM (processed_at - event_created_at)) * 1000),
                0
            )::bigint
        """,
    )
    op.create_check_constraint(
        "ck_payment_state_transitions_evidence_source",
        "payment_state_transitions",
        (
            "evidence_source IN ('provider_payment_api', 'provider_order_api', "
            "'verified_webhook', 'merchant_database', 'recovery_state', "
            "'reconciliation')"
        ),
    )
    op.create_check_constraint(
        "ck_payment_state_transitions_delivery_classification",
        "payment_state_transitions",
        (
            "delivery_classification IN "
            "('on_time', 'delayed', 'reordered', 'provider_reconciled', 'stale')"
        ),
    )
    op.create_check_constraint(
        "ck_payment_state_transitions_delivery_latency_ms",
        "payment_state_transitions",
        "delivery_latency_ms >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payment_state_transitions_delivery_latency_ms",
        "payment_state_transitions",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_state_transitions_delivery_classification",
        "payment_state_transitions",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_state_transitions_evidence_source",
        "payment_state_transitions",
        type_="check",
    )
    op.drop_column("payment_state_transitions", "delivery_latency_ms")
    op.drop_column("payment_state_transitions", "delivery_classification")
    op.drop_column("payment_state_transitions", "evidence_source")
    op.drop_constraint("ck_payment_evidence_reliability", "payment_evidence", type_="check")
    op.drop_column("payment_evidence", "unavailable_reason")
    op.drop_column("payment_evidence", "reliability")
    op.drop_column("payment_evidence", "normalized_fields")
    op.drop_column("payment_evidence", "signature_verified")
    op.drop_constraint("ck_payment_evidence_source", "payment_evidence", type_="check")
    op.create_check_constraint(
        "ck_payment_evidence_source",
        "payment_evidence",
        (
            "source IN ('provider_payment_api', 'provider_order_api', "
            "'verified_webhook', 'merchant_database', 'recovery_state', "
            "'reconciliation')"
        ),
    )
    op.drop_table("payment_event_replay_audits")
