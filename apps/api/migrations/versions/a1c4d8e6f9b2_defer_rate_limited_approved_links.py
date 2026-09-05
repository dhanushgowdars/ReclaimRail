"""Defer already-approved links that Razorpay temporarily rate-limited.

Revision ID: a1c4d8e6f9b2
Revises: f4a8c6d2e9b1
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c4d8e6f9b2"
down_revision: str | Sequence[str] | None = "f4a8c6d2e9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE recovery_actions AS action
        SET status = 'failed', execute_after = CURRENT_TIMESTAMP + INTERVAL '5 minutes'
        FROM recovery_approvals AS approval
        WHERE approval.recovery_action_id = action.id
          AND approval.status = 'approved'
          AND action.action_type = 'create_payment_link'
          AND action.provider_action_id IS NULL
          AND action.last_error LIKE '%status_code=429%'
        """
    )
    op.execute(
        """
        UPDATE recovery_cases AS recovery_case
        SET status = 'ready', next_action_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes',
            closed_at = NULL, close_reason = NULL, version = version + 1
        WHERE EXISTS (
            SELECT 1
            FROM recovery_actions AS action
            JOIN recovery_approvals AS approval ON approval.recovery_action_id = action.id
            WHERE action.recovery_case_id = recovery_case.id
              AND approval.status = 'approved'
              AND action.action_type = 'create_payment_link'
              AND action.provider_action_id IS NULL
              AND action.last_error LIKE '%status_code=429%'
        )
        """
    )


def downgrade() -> None:
    pass
