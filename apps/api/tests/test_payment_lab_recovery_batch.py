from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.recovery import RecoveryChannel
from app.integrations.gemini import RecoveryPlannerSource
from app.services import payment_lab_recovery_batch
from app.services.payment_lab_recovery_batch import (
    PaymentLabRecoveryBatchFailure,
    PaymentLabRecoveryCandidate,
    build_alternate_payment_methods,
    discover_payment_lab_recovery_candidates,
    run_payment_lab_recovery_batch,
)
from app.services.payment_lab_recovery_service import (
    PaymentLabRecoveryConflictError,
    PaymentLabRecoveryRunNotReadyError,
    PaymentLabRecoveryStartDisposition,
    PaymentLabRecoveryStartResult,
)

REFERENCE_TIME = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
RUN_ID_ONE = UUID("92000000-0000-0000-0000-000000000001")
RUN_ID_TWO = UUID("92000000-0000-0000-0000-000000000002")
ATTEMPT_ID_ONE = UUID("92000000-0000-0000-0000-000000000011")
ATTEMPT_ID_TWO = UUID("92000000-0000-0000-0000-000000000012")
CASE_ID_ONE = UUID("92000000-0000-0000-0000-000000000021")
CASE_ID_TWO = UUID("92000000-0000-0000-0000-000000000022")


class SessionContext:
    async def __aenter__(self) -> AsyncSession:
        return AsyncMock(spec=AsyncSession)

    async def __aexit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> bool:
        return False


class SessionFactory:
    def __call__(self) -> SessionContext:
        return SessionContext()


def build_start_result(
    *,
    run_id: UUID = RUN_ID_ONE,
    attempt_id: UUID = ATTEMPT_ID_ONE,
    case_id: UUID = CASE_ID_ONE,
    source: RecoveryPlannerSource = RecoveryPlannerSource.GEMINI,
    fallback_used: bool = False,
) -> PaymentLabRecoveryStartResult:
    return PaymentLabRecoveryStartResult(
        payment_lab_run_id=run_id,
        payment_attempt_id=attempt_id,
        recovery_case_id=case_id,
        disposition=PaymentLabRecoveryStartDisposition.STARTED,
        recovery_case_created=True,
        planner_source=source,
        planner_fallback_used=fallback_used,
    )


def test_alternate_methods_exclude_failed_rail_and_duplicates() -> None:
    assert build_alternate_payment_methods(
        " UPI ",
        supported_methods=("upi", "CARD", "card", "netbanking", ""),
    ) == ("card", "netbanking")


@pytest.mark.asyncio
async def test_discovery_rejects_naive_time_before_database_access() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="timezone-aware"):
        await discover_payment_lab_recovery_candidates(
            session,
            reference_time=datetime(2026, 8, 26, 18, 0),
            batch_size=25,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovers_verified_failure_candidates_in_query_order() -> None:
    query_result = MagicMock()
    query_result.all.return_value = [
        (RUN_ID_ONE, "upi", False),
        (RUN_ID_TWO, "card", True),
    ]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result

    result = await discover_payment_lab_recovery_candidates(
        session,
        reference_time=REFERENCE_TIME,
        batch_size=25,
    )

    assert result == (
        PaymentLabRecoveryCandidate(RUN_ID_ONE, "upi", False),
        PaymentLabRecoveryCandidate(RUN_ID_TWO, "card", True),
    )
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert REFERENCE_TIME - payment_lab_recovery_batch.SIGNED_FAILURE_STABILIZATION_DELAY in (
        statement.compile().params.values()
    )
    assert REFERENCE_TIME - timedelta(seconds=60) in statement.compile().params.values()
    assert REFERENCE_TIME in statement.compile().params.values()


@pytest.mark.asyncio
async def test_batch_runs_gemini_and_deterministic_fallback_without_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = (
        PaymentLabRecoveryCandidate(RUN_ID_ONE, "upi", False),
        PaymentLabRecoveryCandidate(RUN_ID_TWO, "card", True),
    )
    discover = AsyncMock(return_value=candidates)
    start = AsyncMock(
        side_effect=(
            build_start_result(),
            build_start_result(
                run_id=RUN_ID_TWO,
                attempt_id=ATTEMPT_ID_TWO,
                case_id=CASE_ID_TWO,
                source=RecoveryPlannerSource.DETERMINISTIC,
                fallback_used=True,
            ),
        ),
    )
    monkeypatch.setattr(
        payment_lab_recovery_batch,
        "discover_payment_lab_recovery_candidates",
        discover,
    )
    monkeypatch.setattr(
        payment_lab_recovery_batch,
        "start_payment_lab_recovery",
        start,
    )
    provider = MagicMock()

    result = await run_payment_lab_recovery_batch(
        SessionFactory(),  # type: ignore[arg-type]
        reference_time=REFERENCE_TIME,
        provider=provider,
    )

    assert result.discovered == 2
    assert result.started == 2
    assert result.gemini_plans == 1
    assert result.deterministic_plans == 1
    assert result.fallback_plans == 1
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    assert result.skipped == 0

    first_call = start.await_args_list[0].kwargs
    assert first_call["customer_contact_allowed"] is False
    assert first_call["available_channels"] == ()
    assert first_call["alternate_payment_methods"] == (
        "card",
        "netbanking",
        "wallet",
    )
    assert first_call["provider"] is provider
    assert first_call["claim_timeout"] == timedelta(seconds=60)
    second_call = start.await_args_list[1].kwargs
    assert second_call["customer_contact_allowed"] is True
    assert second_call["available_channels"] == (RecoveryChannel.EMAIL,)


@pytest.mark.asyncio
async def test_batch_isolates_stale_conflicting_and_retryable_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = (
        PaymentLabRecoveryCandidate(RUN_ID_ONE, "upi", False),
        PaymentLabRecoveryCandidate(RUN_ID_TWO, "card", False),
        PaymentLabRecoveryCandidate(
            UUID("92000000-0000-0000-0000-000000000003"),
            "wallet",
            False,
        ),
    )
    monkeypatch.setattr(
        payment_lab_recovery_batch,
        "discover_payment_lab_recovery_candidates",
        AsyncMock(return_value=candidates),
    )
    monkeypatch.setattr(
        payment_lab_recovery_batch,
        "start_payment_lab_recovery",
        AsyncMock(
            side_effect=(
                PaymentLabRecoveryRunNotReadyError("claimed elsewhere"),
                PaymentLabRecoveryConflictError("invalid identity"),
                RuntimeError("database temporarily unavailable"),
            ),
        ),
    )

    result = await run_payment_lab_recovery_batch(
        SessionFactory(),  # type: ignore[arg-type]
        reference_time=REFERENCE_TIME,
        provider=None,
    )

    assert result.skipped_run_ids == (RUN_ID_ONE,)
    assert result.permanent_failures == 1
    assert result.retryable_failures == 1
    assert result.failures == (
        PaymentLabRecoveryBatchFailure(
            payment_lab_run_id=RUN_ID_TWO,
            error_type="PaymentLabRecoveryConflictError",
            retryable=False,
        ),
        PaymentLabRecoveryBatchFailure(
            payment_lab_run_id=candidates[2].payment_lab_run_id,
            error_type="RuntimeError",
            retryable=True,
        ),
    )
