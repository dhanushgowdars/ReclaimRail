"""normalize terminal recovery case projections

Revision ID: c8a24f19d6e2
Revises: b6f3d4a12c8e
Create Date: 2026-09-05 11:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8a24f19d6e2"
down_revision: str | Sequence[str] | None = "b6f3d4a12c8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older builds cancelled a rejected/expired action but left its case in an
    # open escalation forever. Use only the latest approval for each case so a
    # later pending or approved request is never overwritten.
    op.execute(
        """
        WITH latest_approval AS (
            SELECT DISTINCT ON (recovery_case_id)
                recovery_case_id,
                status,
                COALESCE(decided_at, expires_at) AS terminal_at
            FROM recovery_approvals
            ORDER BY recovery_case_id, requested_at DESC, id DESC
        )
        UPDATE recovery_cases AS recovery_case
        SET status = 'cancelled',
            next_action_at = NULL,
            active_payment_link_id = NULL,
            closed_at = latest_approval.terminal_at,
            close_reason = CASE latest_approval.status
                WHEN 'rejected' THEN 'approval_rejected_without_execution'
                ELSE 'approval_expired_without_execution'
            END,
            version = recovery_case.version + 1
        FROM latest_approval
        WHERE recovery_case.id = latest_approval.recovery_case_id
          AND latest_approval.status IN ('rejected', 'expired')
          AND recovery_case.status NOT IN ('recovered', 'cancelled', 'exhausted')
        """,
    )

    # A provider-confirmed terminal link state is not awaiting Razorpay. Close
    # the case while retaining the outcome and its evidence observations.
    op.execute(
        """
        UPDATE recovery_cases AS recovery_case
        SET status = 'cancelled',
            next_action_at = NULL,
            active_payment_link_id = NULL,
            closed_at = outcome.occurred_at,
            close_reason = CASE outcome.status
                WHEN 'payment_link_expired' THEN 'payment_link_expired_without_recovery'
                WHEN 'payment_link_cancelled' THEN 'payment_link_cancelled_without_recovery'
                ELSE 'duplicate_collection_prevented'
            END,
            version = recovery_case.version + 1
        FROM recovery_outcomes AS outcome
        WHERE recovery_case.id = outcome.recovery_case_id
          AND outcome.status IN (
              'payment_link_expired',
              'payment_link_cancelled',
              'duplicate_collection_prevented'
          )
          AND recovery_case.status NOT IN ('recovered', 'cancelled', 'exhausted')
        """,
    )


def downgrade() -> None:
    # This migration repairs denormalized lifecycle projections from immutable
    # approval/outcome evidence. Re-opening terminal cases would be unsafe and
    # cannot be inferred unambiguously, so downgrade intentionally preserves it.
    pass
