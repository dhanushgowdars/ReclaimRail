from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.recovery import (
    DEFAULT_RECOVERY_PLANNER_POLICY,
    RecoveryChannel,
    RecoveryPlannerPolicy,
)
from app.integrations.gemini import (
    BoundedRecoveryPlannerResult,
    GeminiRecoveryPlanProvider,
    plan_with_gemini_fallback,
)
from app.services.recovery_approval_service import (
    DEFAULT_APPROVAL_THRESHOLD_MINOR,
    DEFAULT_APPROVAL_WINDOW,
)
from app.services.recovery_plan_service import (
    PersistedRecoveryPlan,
    load_recovery_planning_context,
    plan_and_persist_recovery_case,
)

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class RecoveryAgentExecution:
    planner_result: BoundedRecoveryPlannerResult
    persisted_plan: PersistedRecoveryPlan


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Recovery agent execution time must be timezone-aware",
        )


async def execute_recovery_agent(
    session_factory: SessionFactory,
    *,
    recovery_case_id: UUID,
    available_channels: Sequence[RecoveryChannel],
    alternate_payment_methods: Sequence[str],
    planned_at: datetime,
    provider: GeminiRecoveryPlanProvider | None,
    approval_threshold_minor: int = DEFAULT_APPROVAL_THRESHOLD_MINOR,
    approval_window: timedelta = DEFAULT_APPROVAL_WINDOW,
    planner_policy: RecoveryPlannerPolicy = DEFAULT_RECOVERY_PLANNER_POLICY,
) -> RecoveryAgentExecution:
    """Plan outside a database transaction, then persist through the policy gate."""

    _require_timezone_aware(planned_at)

    async with session_factory() as read_session:
        context = await load_recovery_planning_context(
            read_session,
            recovery_case_id=recovery_case_id,
            available_channels=available_channels,
            alternate_payment_methods=alternate_payment_methods,
            planned_at=planned_at,
        )

    # The provider call happens outside the write transaction. Capture its real
    # wall-clock bounds so the product can distinguish model work from queue,
    # policy, provider and customer waits. These values are evidence, not a UI
    # animation clock.
    planner_started_at = datetime.now(UTC)
    planner_result = await plan_with_gemini_fallback(
        context,
        provider=provider,
        policy=planner_policy,
    )
    planner_completed_at = datetime.now(UTC)

    async with session_factory.begin() as write_session:
        persisted_plan = await plan_and_persist_recovery_case(
            write_session,
            recovery_case_id=recovery_case_id,
            available_channels=available_channels,
            alternate_payment_methods=alternate_payment_methods,
            planned_at=planned_at,
            planner_result=planner_result,
            agent_started_at=planner_started_at,
            agent_completed_at=planner_completed_at,
            approval_threshold_minor=approval_threshold_minor,
            approval_window=approval_window,
        )

    return RecoveryAgentExecution(
        planner_result=planner_result,
        persisted_plan=persisted_plan,
    )
