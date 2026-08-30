from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.domain.recovery import RecoveryChannel
from app.integrations.gemini import RecoveryPlannerSource
from app.services import payment_lab_recovery_service
from app.services.payment_lab_recovery_service import (
    PaymentLabRecoveryStartDisposition,
    _PaymentLabRecoveryClaim,
    start_payment_lab_recovery,
)

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=UTC)
RUN_ID = UUID("91000000-0000-0000-0000-000000000001")
PAYMENT_ATTEMPT_ID = UUID("91000000-0000-0000-0000-000000000002")
CASE_ID = UUID("91000000-0000-0000-0000-000000000003")


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
