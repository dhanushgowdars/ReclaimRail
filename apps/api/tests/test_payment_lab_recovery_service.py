from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import RecoveryCase
from app.domain.incidents import IncidentSeverity
from app.domain.recovery import DEFAULT_RECOVERY_PLANNER_POLICY, RecoveryChannel
from app.integrations.gemini import RecoveryPlannerSource
from app.services import payment_lab_recovery_service
from app.services.payment_lab_recovery_service import (
    PaymentLabRecoveryStartDisposition,
    _claim_payment_lab_recovery,
    _PaymentLabRecoveryClaim,
    start_payment_lab_recovery,
)
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    RecoveryCaseCreationResult,
)
from app.services.recovery_incident_context import ActiveRecoveryIncidentContext

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=UTC)
RUN_ID = UUID("91000000-0000-0000-0000-000000000001")
PAYMENT_ATTEMPT_ID = UUID("91000000-0000-0000-0000-000000000002")
CASE_ID = UUID("91000000-0000-0000-0000-000000000003")
INCIDENT_ID = UUID("91000000-0000-0000-0000-000000000004")


class SessionContext:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


class StubSessionFactory:
    def begin(self) -> SessionContext:
        return SessionContext()


@pytest.fixture(autouse=True)
def no_active_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_load_active_incident_for_run",
        AsyncMock(return_value=None),
    )


def build_claim(
    *,
    disposition: PaymentLabRecoveryStartDisposition = (PaymentLabRecoveryStartDisposition.STARTED),
    should_execute_agent: bool = True,
) -> _PaymentLabRecoveryClaim:
    return _PaymentLabRecoveryClaim(
        payment_lab_run_id=RUN_ID,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        recovery_case_id=CASE_ID,
        disposition=disposition,
        recovery_case_created=True,
        should_execute_agent=should_execute_agent,
    )


@pytest.mark.asyncio
async def test_starts_existing_agent_with_bounded_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = AsyncMock(return_value=build_claim())
    planner_result = MagicMock(
        source=RecoveryPlannerSource.GEMINI,
        fallback_used=False,
    )
    execution = MagicMock(planner_result=planner_result)
    execute_agent = AsyncMock(return_value=execution)

    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_claim_payment_lab_recovery",
        claim,
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "execute_recovery_agent",
        execute_agent,
    )

    session_factory = StubSessionFactory()
    provider = MagicMock()

    result = await start_payment_lab_recovery(
        session_factory,  # type: ignore[arg-type]
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=True,
        available_channels=(RecoveryChannel.EMAIL,),
        alternate_payment_methods=("card", "upi"),
        provider=provider,
    )

    assert result.disposition is PaymentLabRecoveryStartDisposition.STARTED
    assert result.recovery_case_created is True
    assert result.planner_source is RecoveryPlannerSource.GEMINI
    assert result.planner_fallback_used is False

    assert claim.await_args.kwargs["customer_contact_allowed"] is True
    assert execute_agent.await_args.kwargs == {
        "recovery_case_id": CASE_ID,
        "available_channels": (RecoveryChannel.EMAIL,),
        "alternate_payment_methods": ("card", "upi"),
        "planned_at": NOW,
        "provider": provider,
        "approval_threshold_minor": 1_000_000,
        "approval_window": timedelta(minutes=15),
        "planner_policy": DEFAULT_RECOVERY_PLANNER_POLICY,
    }


@pytest.mark.asyncio
async def test_replay_does_not_start_second_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = build_claim(
        disposition=(PaymentLabRecoveryStartDisposition.ALREADY_RUNNING),
        should_execute_agent=False,
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_claim_payment_lab_recovery",
        AsyncMock(return_value=claim),
    )
    execute_agent = AsyncMock()
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "execute_recovery_agent",
        execute_agent,
    )

    result = await start_payment_lab_recovery(
        StubSessionFactory(),  # type: ignore[arg-type]
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=False,
        available_channels=(),
        alternate_payment_methods=(),
        provider=None,
    )

    assert result.disposition is (PaymentLabRecoveryStartDisposition.ALREADY_RUNNING)
    assert result.planner_source is None
    assert result.planner_fallback_used is None
    execute_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_failure_releases_claim_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_claim_payment_lab_recovery",
        AsyncMock(return_value=build_claim()),
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "execute_recovery_agent",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    release_claim = AsyncMock()
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_release_failed_claim",
        release_claim,
    )

    session_factory = StubSessionFactory()

    with pytest.raises(RuntimeError, match="database unavailable"):
        await start_payment_lab_recovery(
            session_factory,  # type: ignore[arg-type]
            payment_lab_run_id=RUN_ID,
            started_at=NOW,
            customer_contact_allowed=False,
            available_channels=(),
            alternate_payment_methods=(),
            provider=None,
        )

    release_claim.assert_awaited_once_with(
        session_factory,
        payment_lab_run_id=RUN_ID,
        recovery_case_id=CASE_ID,
        released_at=NOW,
    )


@pytest.mark.asyncio
async def test_rejects_naive_time_before_claiming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = AsyncMock()
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_claim_payment_lab_recovery",
        claim,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        await start_payment_lab_recovery(
            StubSessionFactory(),  # type: ignore[arg-type]
            payment_lab_run_id=RUN_ID,
            started_at=datetime(2026, 8, 26, 17, 0),
            customer_contact_allowed=False,
            available_channels=(),
            alternate_payment_methods=(),
            provider=None,
        )

    claim.assert_not_awaited()


def optional_scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def build_running_run(*, updated_at: datetime) -> MagicMock:
    run = MagicMock(spec=PaymentLabRun)
    run.id = RUN_ID
    run.status = PaymentLabRunStatus.RECOVERY_RUNNING.value
    run.payment_attempt_id = PAYMENT_ATTEMPT_ID
    run.updated_at = updated_at
    run.version = 3
    return run


def build_open_case() -> MagicMock:
    recovery_case = MagicMock(spec=RecoveryCase)
    recovery_case.id = CASE_ID
    recovery_case.status = "open"
    recovery_case.next_action_at = None
    return recovery_case


@pytest.mark.asyncio
async def test_active_recovery_claim_is_not_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_running_run(updated_at=NOW - timedelta(seconds=30))
    recovery_case = build_open_case()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(run)
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_find_recovery_case",
        AsyncMock(return_value=recovery_case),
    )
    create_case = AsyncMock()
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "create_or_get_recovery_case",
        create_case,
    )

    claim = await _claim_payment_lab_recovery(
        session,
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=False,
        claim_timeout=timedelta(seconds=60),
    )

    assert claim.disposition is PaymentLabRecoveryStartDisposition.ALREADY_RUNNING
    assert claim.should_execute_agent is False
    assert run.version == 3
    create_case.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_recovery_claim_is_reclaimed_for_plannable_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_running_run(updated_at=NOW - timedelta(seconds=61))
    recovery_case = build_open_case()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(run)
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_find_recovery_case",
        AsyncMock(return_value=recovery_case),
    )
    create_case = AsyncMock(
        return_value=RecoveryCaseCreationResult(
            disposition=RecoveryCaseCreationDisposition.EXISTING,
            recovery_case=recovery_case,
            audit_event=None,
        ),
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "create_or_get_recovery_case",
        create_case,
    )

    claim = await _claim_payment_lab_recovery(
        session,
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=False,
        claim_timeout=timedelta(seconds=60),
    )

    assert claim.disposition is PaymentLabRecoveryStartDisposition.STARTED
    assert claim.should_execute_agent is True
    assert claim.recovery_case_created is False
    assert run.status == PaymentLabRunStatus.RECOVERY_RUNNING.value
    assert run.updated_at == NOW
    assert run.version == 4
    create_case.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_case_persists_active_incident_as_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_running_run(updated_at=NOW - timedelta(seconds=61))
    run.status = PaymentLabRunStatus.PAYMENT_ATTEMPTED.value
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(run)
    recovery_case = build_open_case()
    create_case = AsyncMock(
        return_value=RecoveryCaseCreationResult(
            disposition=RecoveryCaseCreationDisposition.CREATED,
            recovery_case=recovery_case,
            audit_event=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "create_or_get_recovery_case",
        create_case,
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_load_active_incident_for_run",
        AsyncMock(
            return_value=ActiveRecoveryIncidentContext(
                incident_id=INCIDENT_ID,
                severity=IncidentSeverity.HIGH,
                scope="payment_method",
                dimension_value="netbanking",
            ),
        ),
    )

    claim = await _claim_payment_lab_recovery(
        session,
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=False,
        claim_timeout=timedelta(seconds=60),
    )

    assert claim.disposition is PaymentLabRecoveryStartDisposition.STARTED
    create_case.assert_awaited_once_with(
        session,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        opened_at=NOW,
        customer_contact_allowed=False,
        source_incident_id=INCIDENT_ID,
    )


@pytest.mark.asyncio
async def test_scheduled_wait_is_not_reclaimed_after_worker_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_running_run(updated_at=NOW - timedelta(seconds=61))
    recovery_case = build_open_case()
    recovery_case.status = "waiting"
    recovery_case.next_action_at = NOW + timedelta(minutes=15)
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(run)
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_find_recovery_case",
        AsyncMock(return_value=recovery_case),
    )
    create_case = AsyncMock()
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "create_or_get_recovery_case",
        create_case,
    )

    claim = await _claim_payment_lab_recovery(
        session,
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=False,
        claim_timeout=timedelta(seconds=60),
    )

    assert claim.disposition is PaymentLabRecoveryStartDisposition.ALREADY_PLANNED
    assert claim.should_execute_agent is False
    assert run.version == 3
    create_case.assert_not_awaited()


@pytest.mark.asyncio
async def test_due_scheduled_wait_is_reclaimed_for_one_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_running_run(updated_at=NOW - timedelta(seconds=5))
    recovery_case = build_open_case()
    recovery_case.status = "waiting"
    recovery_case.next_action_at = NOW
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = optional_scalar_result(run)
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "_find_recovery_case",
        AsyncMock(return_value=recovery_case),
    )
    create_case = AsyncMock(
        return_value=RecoveryCaseCreationResult(
            disposition=RecoveryCaseCreationDisposition.EXISTING,
            recovery_case=recovery_case,
            audit_event=None,
        ),
    )
    monkeypatch.setattr(
        payment_lab_recovery_service,
        "create_or_get_recovery_case",
        create_case,
    )

    claim = await _claim_payment_lab_recovery(
        session,
        payment_lab_run_id=RUN_ID,
        started_at=NOW,
        customer_contact_allowed=False,
        claim_timeout=timedelta(seconds=60),
    )

    assert claim.disposition is PaymentLabRecoveryStartDisposition.STARTED
    assert claim.should_execute_agent is True
    assert run.status == PaymentLabRunStatus.RECOVERY_RUNNING.value
    assert run.updated_at == NOW
    assert run.version == 4
    create_case.assert_awaited_once()
