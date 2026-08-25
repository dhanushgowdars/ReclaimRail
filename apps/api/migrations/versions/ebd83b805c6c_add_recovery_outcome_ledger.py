"""add recovery outcome ledger

Revision ID: ebd83b805c6c
Revises: e0b722e32771
Create Date: 2026-08-25 20:10:14.346892

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ebd83b805c6c"
down_revision: str | Sequence[str] | None = "e0b722e32771"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recovery_outcomes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recovery_case_id", sa.UUID(), nullable=False),
        sa.Column("payment_attempt_id", sa.UUID(), nullable=False),
        sa.Column("recovery_action_id", sa.UUID(), nullable=True),
        sa.Column(
            "provider_payment_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "payment_link_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "provider_outcome_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column(
            "attribution",
            sa.String(length=48),
            nullable=False,
        ),
        sa.Column(
            "original_amount_minor",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "gross_recovered_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reversed_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "duplicate_collection_prevented_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "evidence_event_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "outcome_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
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
        sa.Column(
            "version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "(status = 'recovered' "
                "AND gross_recovered_minor > 0 "
                "AND attribution = 'direct_payment_link' "
                "AND recovery_action_id IS NOT NULL "
                "AND payment_link_id IS NOT NULL) "
                "OR (status = 'reversed' "
                "AND gross_recovered_minor > 0 "
                "AND reversed_minor > 0 "
                "AND attribution = 'direct_payment_link' "
                "AND recovery_action_id IS NOT NULL "
                "AND payment_link_id IS NOT NULL) "
                "OR (status = 'duplicate_collection_prevented' "
                "AND gross_recovered_minor = 0 "
                "AND reversed_minor = 0 "
                "AND duplicate_collection_prevented_minor > 0 "
                "AND attribution = 'late_authorization_safety') "
                "OR (status IN ("
                "'payment_link_pending', "
                "'payment_link_expired', "
                "'payment_link_cancelled', "
                "'unresolved'"
                ") "
                "AND gross_recovered_minor = 0 "
                "AND reversed_minor = 0 "
                "AND duplicate_collection_prevented_minor = 0 "
                "AND attribution = 'none')"
            ),
            name="ck_recovery_outcomes_financial_semantics",
        ),
        sa.CheckConstraint(
            ("attribution IN ('direct_payment_link', 'late_authorization_safety', 'none')"),
            name="ck_recovery_outcomes_attribution",
        ),
        sa.CheckConstraint(
            (
                "status IN ("
                "'payment_link_pending', "
                "'recovered', "
                "'payment_link_expired', "
                "'payment_link_cancelled', "
                "'duplicate_collection_prevented', "
                "'reversed', "
                "'unresolved'"
                ")"
            ),
            name="ck_recovery_outcomes_status",
        ),
        sa.CheckConstraint(
            "char_length(outcome_fingerprint) = 64",
            name="ck_recovery_outcomes_fingerprint_length",
        ),
        sa.CheckConstraint(
            ("duplicate_collection_prevented_minor <= original_amount_minor"),
            name="ck_recovery_outcomes_prevented_within_original",
        ),
        sa.CheckConstraint(
            "duplicate_collection_prevented_minor >= 0",
            name="ck_recovery_outcomes_duplicate_prevented",
        ),
        sa.CheckConstraint(
            "gross_recovered_minor <= original_amount_minor",
            name="ck_recovery_outcomes_gross_within_original",
        ),
        sa.CheckConstraint(
            "gross_recovered_minor >= 0",
            name="ck_recovery_outcomes_gross_recovered",
        ),
        sa.CheckConstraint(
            "original_amount_minor > 0",
            name="ck_recovery_outcomes_original_amount",
        ),
        sa.CheckConstraint(
            "reversed_minor <= gross_recovered_minor",
            name="ck_recovery_outcomes_reversal_within_gross",
        ),
        sa.CheckConstraint(
            "reversed_minor >= 0",
            name="ck_recovery_outcomes_reversed",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_recovery_outcomes_version",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name=op.f("fk_recovery_outcomes_payment_attempt_id_payment_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_action_id"],
            ["recovery_actions.id"],
            name=op.f("fk_recovery_outcomes_recovery_action_id_recovery_actions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_case_id"],
            ["recovery_cases.id"],
            name=op.f("fk_recovery_outcomes_recovery_case_id_recovery_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_recovery_outcomes"),
        ),
        sa.UniqueConstraint(
            "recovery_case_id",
            name="uq_recovery_outcomes_recovery_case_id",
        ),
    )
    op.create_index(
        "ix_recovery_outcomes_payment_attempt",
        "recovery_outcomes",
        ["payment_attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_outcomes_payment_link",
        "recovery_outcomes",
        ["payment_link_id"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_outcomes_status_updated",
        "recovery_outcomes",
        ["status", "updated_at"],
        unique=False,
    )

    op.create_table(
        "recovery_outcome_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "recovery_outcome_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "recovery_action_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column(
            "attribution",
            sa.String(length=48),
            nullable=False,
        ),
        sa.Column(
            "gross_recovered_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reversed_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "duplicate_collection_prevented_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "payment_link_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "provider_outcome_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "evidence_event_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "observation_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            ("attribution IN ('direct_payment_link', 'late_authorization_safety', 'none')"),
            name="ck_recovery_outcome_observations_attribution",
        ),
        sa.CheckConstraint(
            (
                "status IN ("
                "'payment_link_pending', "
                "'recovered', "
                "'payment_link_expired', "
                "'payment_link_cancelled', "
                "'duplicate_collection_prevented', "
                "'reversed', "
                "'unresolved'"
                ")"
            ),
            name="ck_recovery_outcome_observations_status",
        ),
        sa.CheckConstraint(
            "char_length(observation_fingerprint) = 64",
            name=("ck_recovery_outcome_observations_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "duplicate_collection_prevented_minor >= 0",
            name=("ck_recovery_outcome_observations_duplicate_prevented"),
        ),
        sa.CheckConstraint(
            "gross_recovered_minor >= 0",
            name="ck_recovery_outcome_observations_gross_recovered",
        ),
        sa.CheckConstraint(
            "reversed_minor <= gross_recovered_minor",
            name=("ck_recovery_outcome_observations_reversal_within_gross"),
        ),
        sa.CheckConstraint(
            "reversed_minor >= 0",
            name="ck_recovery_outcome_observations_reversed",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_action_id"],
            ["recovery_actions.id"],
            name=op.f("fk_recovery_outcome_observations_recovery_action_id_recovery_actions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_outcome_id"],
            ["recovery_outcomes.id"],
            name=op.f("fk_recovery_outcome_observations_recovery_outcome_id_recovery_outcomes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_recovery_outcome_observations"),
        ),
        sa.UniqueConstraint(
            "recovery_outcome_id",
            "observation_fingerprint",
            name=("uq_recovery_outcome_observations_outcome_fingerprint"),
        ),
    )
    op.create_index(
        "ix_recovery_outcome_observations_outcome_occurred",
        "recovery_outcome_observations",
        ["recovery_outcome_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_outcome_observations_status_occurred",
        "recovery_outcome_observations",
        ["status", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_recovery_outcome_observations_status_occurred",
        table_name="recovery_outcome_observations",
    )
    op.drop_index(
        "ix_recovery_outcome_observations_outcome_occurred",
        table_name="recovery_outcome_observations",
    )
    op.drop_table("recovery_outcome_observations")

    op.drop_index(
        "ix_recovery_outcomes_status_updated",
        table_name="recovery_outcomes",
    )
    op.drop_index(
        "ix_recovery_outcomes_payment_link",
        table_name="recovery_outcomes",
    )
    op.drop_index(
        "ix_recovery_outcomes_payment_attempt",
        table_name="recovery_outcomes",
    )
    op.drop_table("recovery_outcomes")
