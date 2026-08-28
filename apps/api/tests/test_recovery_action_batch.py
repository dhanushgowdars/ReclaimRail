import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
)
from app.services import recovery_action_batch
from app.services.recovery_action_batch import (
    RecoveryActionBatchResult,
    discover_executable_recovery_action_ids,
    run_recovery_action_batch,
)
from app.services.recovery_action_executor import (
    RecoveryActionExecutionDisposition,
    RecoveryActionExecutionResult,
    RecoveryActionInProgressError,
    RecoveryActionNotDueError,
    RecoveryActionNotExecutableError,
    RecoveryActionProviderFailure,
)

NOW = datetime(
    2026,
    8,
    25,
    18,
    0,
    tzinfo=UTC,
)

ACTION_IDS = tuple(
    UUID(
        f"92000000-0000-0000-0000-{number:012d}",
    )
    for number in range(1, 6)
)


def scalar_result(
    values: tuple[UUID, ...],
) -> MagicMock:
    result = MagicMock()

    result.scalars.return_value.all.return_value = list(values)

    return result


def execution_result(
    action_id: UUID,
    disposition: RecoveryActionExecutionDisposition,
) -> RecoveryActionExecutionResult:
    return RecoveryActionExecutionResult(
        action_id=action_id,
        recovery_case_id=UUID(
            "92000000-0000-0000-0000-999999999999",
        ),
        disposition=disposition,
    )


class SessionContext:
    def __init__(
        self,
        session: object,
    ) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


class StubSessionFactory:
    def __init__(self) -> None:
        self.expiry_session = AsyncMock(
            spec=AsyncSession,
        )
        self.expiry_session.execute.return_value = scalar_result(())
        self.discovery_session = MagicMock(
            name="discovery_session",
        )
        self.open_count = 0

    def __call__(self) -> SessionContext:
        self.open_count += 1

        return SessionContext(
            self.discovery_session,
        )

    def begin(self) -> SessionContext:
        return SessionContext(
            self.expiry_session,
        )


@pytest.mark.asyncio
async def test_discovers_executable_action_ids_in_query_order() -> None:
    session = AsyncMock(
        spec=AsyncSession,
    )

    session.execute.return_value = scalar_result(
        ACTION_IDS[:3],
    )

    result = await discover_executable_recovery_action_ids(
        session,
        reference_time=NOW,
        batch_size=25,
        claim_timeout=timedelta(minutes=2),
        maximum_attempts=3,
    )

    assert result == ACTION_IDS[:3]
    session.execute.assert_awaited_once()


@pytest.mark.parametrize(
    (
        "reference_time",
        "batch_size",
        "claim_timeout",
        "maximum_attempts",
    ),
    [
        (
            datetime(2026, 8, 25, 18, 0),
            25,
            timedelta(minutes=2),
            3,
        ),
        (
            NOW,
            0,
            timedelta(minutes=2),
            3,
        ),
        (
            NOW,
            101,
            timedelta(minutes=2),
            3,
        ),
        (
            NOW,
            25,
            timedelta(0),
            3,
        ),
        (
            NOW,
            25,
            timedelta(minutes=2),
            0,
        ),
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_discovery_configuration(
    reference_time: datetime,
    batch_size: int,
    claim_timeout: timedelta,
    maximum_attempts: int,
) -> None:
    session = AsyncMock(
        spec=AsyncSession,
    )

    with pytest.raises(ValueError):
        await discover_executable_recovery_action_ids(
            session,
            reference_time=reference_time,
            batch_size=batch_size,
            claim_timeout=claim_timeout,
            maximum_attempts=maximum_attempts,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_reports_success_replay_and_policy_denials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_ids = ACTION_IDS[:4]

    monkeypatch.setattr(
        recovery_action_batch,
        "discover_executable_recovery_action_ids",
        AsyncMock(
            return_value=action_ids,
        ),
    )

    execute = AsyncMock(
        side_effect=[
            execution_result(
                action_ids[0],
                RecoveryActionExecutionDisposition.SUCCEEDED,
            ),
            execution_result(
                action_ids[1],
                RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED,
            ),
            execution_result(
                action_ids[2],
                RecoveryActionExecutionDisposition.POLICY_BLOCKED,
            ),
            execution_result(
                action_ids[3],
                RecoveryActionExecutionDisposition.POLICY_STOPPED,
            ),
        ],
    )

    monkeypatch.setattr(
        recovery_action_batch,
        "execute_recovery_payment_link_action",
        execute,
    )

    session_factory = StubSessionFactory()

    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )

    result = await run_recovery_action_batch(
        session_factory,  # type: ignore[arg-type]
        provider=provider,
        reference_time=NOW,
    )

    assert result.discovered == 4
    assert result.succeeded == 1
    assert result.already_succeeded == 1
    assert result.policy_denied == 2
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    assert result.skipped == 0
    assert execute.await_count == 4
    assert session_factory.open_count == 1


@pytest.mark.asyncio
async def test_batch_classifies_provider_and_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_ids = ACTION_IDS[:3]

    monkeypatch.setattr(
        recovery_action_batch,
        "discover_executable_recovery_action_ids",
        AsyncMock(
            return_value=action_ids,
        ),
    )

    monkeypatch.setattr(
        recovery_action_batch,
        "execute_recovery_payment_link_action",
        AsyncMock(
            side_effect=[
                RecoveryActionProviderFailure(
                    "temporary provider failure",
                    retryable=True,
                    status_code=503,
                ),
                RecoveryActionProviderFailure(
                    "permanent provider failure",
                    retryable=False,
                    status_code=400,
                ),
                RuntimeError(
                    "unexpected database failure",
                ),
            ],
        ),
    )

    result = await run_recovery_action_batch(
        StubSessionFactory(),  # type: ignore[arg-type]
        provider=MagicMock(
            spec=RazorpayPaymentLinkProvider,
        ),
        reference_time=NOW,
    )

    assert result.discovered == 3
    assert result.retryable_failures == 1
    assert result.permanent_failures == 2

    assert [failure.error_type for failure in result.failures] == [
        "RecoveryActionProviderFailure",
        "RecoveryActionProviderFailure",
        "RuntimeError",
    ]


@pytest.mark.asyncio
async def test_batch_skips_actions_changed_by_competing_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_ids = ACTION_IDS[:3]

    monkeypatch.setattr(
        recovery_action_batch,
        "discover_executable_recovery_action_ids",
        AsyncMock(
            return_value=action_ids,
        ),
    )

    monkeypatch.setattr(
        recovery_action_batch,
        "execute_recovery_payment_link_action",
        AsyncMock(
            side_effect=[
                RecoveryActionInProgressError(
                    "claimed",
                ),
                RecoveryActionNotDueError(
                    "rescheduled",
                ),
                RecoveryActionNotExecutableError(
                    "state changed",
                ),
            ],
        ),
    )

    result = await run_recovery_action_batch(
        StubSessionFactory(),  # type: ignore[arg-type]
        provider=MagicMock(
            spec=RazorpayPaymentLinkProvider,
        ),
        reference_time=NOW,
    )

    assert result.skipped_action_ids == action_ids
    assert result.skipped == 3
    assert result.failures == ()


@pytest.mark.asyncio
async def test_batch_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_action_batch,
        "discover_executable_recovery_action_ids",
        AsyncMock(
            return_value=(ACTION_IDS[0],),
        ),
    )

    monkeypatch.setattr(
        recovery_action_batch,
        "execute_recovery_payment_link_action",
        AsyncMock(
            side_effect=asyncio.CancelledError(),
        ),
    )

    with pytest.raises(
        asyncio.CancelledError,
    ):
        await run_recovery_action_batch(
            StubSessionFactory(),  # type: ignore[arg-type]
            provider=MagicMock(
                spec=RazorpayPaymentLinkProvider,
            ),
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_batch_rejects_naive_time_before_opening_session() -> None:
    session_factory = StubSessionFactory()

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        await run_recovery_action_batch(
            session_factory,  # type: ignore[arg-type]
            provider=MagicMock(
                spec=RazorpayPaymentLinkProvider,
            ),
            reference_time=datetime(
                2026,
                8,
                25,
                18,
                0,
            ),
        )

    assert session_factory.open_count == 0


def test_empty_batch_has_zero_counters() -> None:
    result = RecoveryActionBatchResult(
        discovered_action_ids=(),
        execution_results=(),
        failures=(),
        skipped_action_ids=(),
    )

    assert result.discovered == 0
    assert result.succeeded == 0
    assert result.already_succeeded == 0
    assert result.policy_denied == 0
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    assert result.skipped == 0
