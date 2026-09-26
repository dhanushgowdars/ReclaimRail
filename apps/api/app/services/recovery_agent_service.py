import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.investigation import InvestigationBudgets
from app.domain.recovery import (
    DEFAULT_RECOVERY_PLANNER_POLICY,
    RecoveryChannel,
    RecoveryPlannerPolicy,
)
from app.integrations.gemini import (
    BoundedRecoveryPlannerResult,
    EvidenceInvestigatorProvider,
    GeminiRecoveryPlanProvider,
    plan_with_gemini_fallback,
)
from app.services.recovery_approval_service import (
    DEFAULT_APPROVAL_THRESHOLD_MINOR,
    DEFAULT_APPROVAL_WINDOW,
)
from app.services.recovery_investigator_service import (
    RecoveryInvestigationResult,
    run_shadow_investigation,
)
from app.services.recovery_plan_service import (
    PersistedRecoveryPlan,
    load_recovery_planning_context,
    plan_and_persist_recovery_case,
)

SessionFactory = async_sessionmaker[AsyncSession]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryAgentExecution:
    planner_result: BoundedRecoveryPlannerResult
    persisted_plan: PersistedRecoveryPlan
    investigation_result: RecoveryInvestigationResult | None = None


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
    investigator_provider: EvidenceInvestigatorProvider | None = None,
    investigator_budgets: InvestigationBudgets | None = None,
    approval_threshold_minor: int = DEFAULT_APPROVAL_THRESHOLD_MINOR,
    approval_window: timedelta = DEFAULT_APPROVAL_WINDOW,
    planner_policy: RecoveryPlannerPolicy = DEFAULT_RECOVERY_PLANNER_POLICY,
) -> RecoveryAgentExecution:
    """Plan outside a database transaction, then persist through the policy gate."""

    _require_timezone_aware(planned_at)

    investigation_result: RecoveryInvestigationResult | None = None
    try:
        investigation_result = await run_shadow_investigation(
            session_factory,
            recovery_case_id=recovery_case_id,
            provider=investigator_provider,
            started_at=planned_at,
            budgets=investigator_budgets,
        )
    except Exception:  # noqa: BLE001 - shadow analysis must never block recovery
        LOGGER.exception(
            "Shadow evidence investigation failed without affecting recovery case %s",
            recovery_case_id,
        )

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
        investigation_result=investigation_result,
    )
