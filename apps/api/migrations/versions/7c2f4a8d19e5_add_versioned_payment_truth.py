"""add versioned payment truth

Revision ID: 7c2f4a8d19e5
Revises: c2e8a4d6b1f3
Create Date: 2026-09-22 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c2f4a8d19e5"
down_revision: str | Sequence[str] | None = "c2e8a4d6b1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_attempt_id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.Column("fact_name", sa.String(length=128), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fresh_until IS NULL OR fresh_until > observed_at",
            name="ck_payment_evidence_freshness",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_payment_evidence_sha256",
        ),
        sa.CheckConstraint(
            (
                "source IN ('provider_payment_api', 'provider_order_api', "
                "'verified_webhook', 'merchant_database', 'recovery_state', "
                "'reconciliation')"
            ),
            name="ck_payment_evidence_source",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name=op.f("fk_payment_evidence_payment_attempt_id_payment_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f("fk_payment_evidence_recovery_case_id_recovery_cases"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_evidence")),
        sa.UniqueConstraint(
            "payment_attempt_id",
            "source",
            "source_reference",
            "fact_name",
            "content_sha256",
            name="uq_payment_evidence_fact_identity",
        ),
    )
    op.create_index(
        "ix_payment_evidence_attempt_observed",
        "payment_evidence",
        ["payment_attempt_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_evidence_case_observed",
        "payment_evidence",
        ["recovery_case_id", "observed_at"],
        unique=False,
    )

    op.create_table(
        "payment_truth_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_attempt_id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conflict_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False),
        sa.Column("resolver_version", sa.String(length=32), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence_digest ~ '^[0-9a-f]{64}$'",
            name="ck_payment_truth_evidence_digest",
        ),
        sa.CheckConstraint(
            (
                "state IN ('payment_confirmed', 'payment_failed', 'payment_pending', "
                "'outcome_unknown', 'source_conflict', 'late_authorization', "
                "'recovery_already_active', 'recovery_confirmed', "
                "'manual_investigation_required')"
            ),
            name="ck_payment_truth_state",
        ),
        sa.CheckConstraint("version >= 1", name="ck_payment_truth_version"),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name=op.f("fk_payment_truth_snapshots_payment_attempt_id_payment_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f("fk_payment_truth_snapshots_recovery_case_id_recovery_cases"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_truth_snapshots")),
        sa.UniqueConstraint(
            "payment_attempt_id",
            "evidence_digest",
            "state",
            name="uq_payment_truth_attempt_digest_state",
        ),
        sa.UniqueConstraint(
            "payment_attempt_id",
            "version",
            name="uq_payment_truth_attempt_version",
        ),
    )
    op.create_index(
        "ix_payment_truth_attempt_resolved",
        "payment_truth_snapshots",
        ["payment_attempt_id", "resolved_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_truth_case_resolved",
        "payment_truth_snapshots",
        ["recovery_case_id", "resolved_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_truth_case_resolved",
        table_name="payment_truth_snapshots",
    )
    op.drop_index(
        "ix_payment_truth_attempt_resolved",
        table_name="payment_truth_snapshots",
    )
    op.drop_table("payment_truth_snapshots")
    op.drop_index("ix_payment_evidence_case_observed", table_name="payment_evidence")
    op.drop_index("ix_payment_evidence_attempt_observed", table_name="payment_evidence")
    op.drop_table("payment_evidence")
