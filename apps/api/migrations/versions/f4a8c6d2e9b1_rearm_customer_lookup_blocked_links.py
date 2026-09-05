"""Re-arm approved links blocked by optional customer lookup.

Revision ID: f4a8c6d2e9b1
Revises: d91f4b7a2c10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4a8c6d2e9b1"
down_revision: str | Sequence[str] | None = "d91f4b7a2c10"
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
          AND action.status = 'failed'
          AND action.provider_action_id IS NULL
          AND action.execution_attempt_count >= 3
        """
    )
    op.execute(
        """
        UPDATE recovery_cases AS recovery_case
        SET status = 'ready', next_action_at = CURRENT_TIMESTAMP,
            closed_at = NULL, close_reason = NULL, version = version + 1
        WHERE EXISTS (
            SELECT 1 FROM recovery_actions AS action
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
