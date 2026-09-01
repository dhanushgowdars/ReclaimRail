from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.domain.payments import PaymentState
from app.domain.recovery import (
    PaymentFailureEvidence,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlanningContext,
    build_deterministic_recovery_plan,
)
from app.integrations.gemini import (
    BoundedRecoveryPlannerResult,
    GeminiPlannerFallbackReason,
    RecoveryPlannerSource,
)
from app.services import recovery_agent_service
from app.services.recovery_agent_service import execute_recovery_agent
from app.services.recovery_plan_service import PersistedRecoveryPlan

NOW = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
CASE_ID = UUID("83000000-0000-0000-0000-000000000001")
PAYMENT_ID = UUID("83000000-0000-0000-0000-000000000002")


def create_context() -> RecoveryPlanningContext:
    return RecoveryPlanningContext(
        case=RecoveryCaseSnapshot(
            case_id=CASE_ID,
            payment_attempt_id=PAYMENT_ID,
            provider_payment_id="pay_recovery_agent_test",
            payment_state=PaymentState.FAILED,
            amount_minor=90_000,
            currency="INR",
            payment_method="upi",
            status=RecoveryCaseStatus.OPEN,
            recovery_attempt_count=0,
            customer_contact_allowed=True,
        ),
        failure=PaymentFailureEvidence(
            error_code="BAD_REQUEST_ERROR",
            error_source="customer",
            error_step="payment_authentication",
            error_reason="payment_failed",
            failure_count=1,
            first_failed_at=NOW - timedelta(minutes=5),
            last_failed_at=NOW - timedelta(minutes=5),
        ),
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
    )


def create_planner_result() -> BoundedRecoveryPlannerResult:
    context = create_context()

    return BoundedRecoveryPlannerResult(
        plan=build_deterministic_recovery_plan(context),
        source=RecoveryPlannerSource.DETERMINISTIC,
        model_name=None,
        fallback_used=True,
        fallback_reason=GeminiPlannerFallbackReason.NOT_CONFIGURED,
    )


class SessionContext:
    def __init__(
        self,
        session: object,
        label: str,
        events: list[str],
    ) -> None:
        self._session = session
        self._label = label
        self._events = events

    async def __aenter__(self) -> object:
        self._events.append(f"{self._label}_enter")
        return self._session

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        suffix = "error" if exception is not None else "exit"
        self._events.append(f"{self._label}_{suffix}")


class StubSessionFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.read_session = MagicMock(name="read_session")
        self.write_session = MagicMock(name="write_session")
        self.begin_count = 0

    def __call__(self) -> SessionContext:
        return SessionContext(
            self.read_session,
            "read",
            self.events,
        )

    def begin(self) -> SessionContext:
        self.begin_count += 1

        return SessionContext(
            self.write_session,
            "write",
            self.events,
        )


@pytest.mark.asyncio
async def test_calls_planner_only_after_read_session_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    session_factory = StubSessionFactory(events)
    context = create_context()
    planner_result = create_planner_result()
    persisted_plan = MagicMock(spec=PersistedRecoveryPlan)
    provider = MagicMock(name="provider")
    persisted_kwargs: dict[str, object] = {}

    async def load_context(
        *args: object,
        **kwargs: object,
    ) -> RecoveryPlanningContext:
        events.append("load")
        return context

    async def plan(
        *args: object,
        **kwargs: object,
    ) -> BoundedRecoveryPlannerResult:
        events.append("plan")

        assert events[-2] == "read_exit"
        assert kwargs["provider"] is provider

        return planner_result

    async def persist(
        *args: object,
        **kwargs: object,
    ) -> PersistedRecoveryPlan:
        events.append("persist")

        assert kwargs["planner_result"] is planner_result
        persisted_kwargs.update(kwargs)

        return persisted_plan

    monkeypatch.setattr(
        recovery_agent_service,
        "load_recovery_planning_context",
        load_context,
    )
    monkeypatch.setattr(
        recovery_agent_service,
        "plan_with_gemini_fallback",
        plan,
    )
    monkeypatch.setattr(
        recovery_agent_service,
        "plan_and_persist_recovery_case",
        persist,
    )

    result = await execute_recovery_agent(
        session_factory,  # type: ignore[arg-type]
        recovery_case_id=CASE_ID,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card",),
        planned_at=NOW,
        provider=provider,  # type: ignore[arg-type]
    )

    assert result.planner_result is planner_result
    assert result.persisted_plan is persisted_plan

    agent_started_at = persisted_kwargs["agent_started_at"]
    agent_completed_at = persisted_kwargs["agent_completed_at"]
    assert isinstance(agent_started_at, datetime)
    assert isinstance(agent_completed_at, datetime)
    assert agent_started_at.tzinfo is not None
    assert agent_completed_at.tzinfo is not None
    assert (
        agent_started_at
        <= agent_completed_at
    )

    assert events == [
        "read_enter",
        "load",
        "read_exit",
        "plan",
        "write_enter",
        "persist",
        "write_exit",
    ]


@pytest.mark.asyncio
async def test_planner_failure_does_not_open_write_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    session_factory = StubSessionFactory(events)

    monkeypatch.setattr(
        recovery_agent_service,
        "load_recovery_planning_context",
        AsyncMock(return_value=create_context()),
    )
    monkeypatch.setattr(
        recovery_agent_service,
        "plan_with_gemini_fallback",
        AsyncMock(
            side_effect=RuntimeError(
                "unexpected planner failure",
            ),
        ),
    )

    persist = AsyncMock()

    monkeypatch.setattr(
        recovery_agent_service,
        "plan_and_persist_recovery_case",
        persist,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected planner failure",
    ):
        await execute_recovery_agent(
            session_factory,  # type: ignore[arg-type]
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=NOW,
            provider=None,
        )

    assert session_factory.begin_count == 0
    persist.assert_not_awaited()
    assert events == [
        "read_enter",
        "read_exit",
    ]


@pytest.mark.asyncio
async def test_persistence_failure_exits_transaction_with_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    session_factory = StubSessionFactory(events)

    monkeypatch.setattr(
        recovery_agent_service,
        "load_recovery_planning_context",
        AsyncMock(return_value=create_context()),
    )
    monkeypatch.setattr(
        recovery_agent_service,
        "plan_with_gemini_fallback",
        AsyncMock(return_value=create_planner_result()),
    )
    monkeypatch.setattr(
        recovery_agent_service,
        "plan_and_persist_recovery_case",
        AsyncMock(
            side_effect=RuntimeError(
                "database failure",
            ),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="database failure",
    ):
        await execute_recovery_agent(
            session_factory,  # type: ignore[arg-type]
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=NOW,
            provider=None,
        )

    assert events == [
        "read_enter",
        "read_exit",
        "write_enter",
        "write_error",
    ]


@pytest.mark.asyncio
async def test_rejects_naive_time_before_opening_session() -> None:
    events: list[str] = []
    session_factory = StubSessionFactory(events)

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        await execute_recovery_agent(
            session_factory,  # type: ignore[arg-type]
            recovery_case_id=CASE_ID,
            available_channels=(),
            alternate_payment_methods=(),
            planned_at=datetime(
                2026,
                8,
                25,
                14,
                0,
            ),
            provider=None,
        )

    assert events == []
    assert session_factory.begin_count == 0
