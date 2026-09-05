"""Re-arm approved requests that were throttled before link creation.

Revision ID: c2e8a4d6b1f3
Revises: a1c4d8e6f9b2
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2e8a4d6b1f3"
down_revision: str | Sequence[str] | None = "a1c4d8e6f9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE recovery_actions AS action
        SET status = 'allowed', execution_attempt_count = 0,
            execute_after = NULL, started_at = NULL, completed_at = NULL, last_error = NULL
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
        SET status = 'ready', next_action_at = CURRENT_TIMESTAMP,
            closed_at = NULL, close_reason = NULL, version = version + 1
        WHERE EXISTS (
            SELECT 1
            FROM recovery_actions AS action
            JOIN recovery_approvals AS approval ON approval.recovery_action_id = action.id
            WHERE action.recovery_case_id = recovery_case.id
              AND approval.status = 'approved'
              AND action.action_type = 'create_payment_link'
              AND action.status = 'allowed'
              AND action.execution_attempt_count = 0
              AND action.provider_action_id IS NULL
        )
        """
    )


def downgrade() -> None:
    pass
