from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services import recovery_message_batch
from app.services.recovery_action_executor import (
    RecoveryActionExecutionDisposition,
    RecoveryActionExecutionResult,
    RecoveryActionNotDueError,
)
from app.services.recovery_message_batch import (
    RecoveryMessageBatchResult,
    discover_recovery_message_action_ids,
    run_recovery_message_batch,
)
from app.services.recovery_message_executor import (
    RecoveryMessageProviderFailure,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

ACTION_ID_ONE = UUID("10000000-0000-0000-0000-000000000001")
ACTION_ID_TWO = UUID("10000000-0000-0000-0000-000000000002")
ACTION_ID_THREE = UUID("10000000-0000-0000-0000-000000000003")

CASE_ID = UUID("20000000-0000-0000-0000-000000000001")


def build_execution_result(
    disposition: RecoveryActionExecutionDisposition,
    *,
    action_id: UUID = ACTION_ID_ONE,
) -> RecoveryActionExecutionResult:
    return RecoveryActionExecutionResult(
        action_id=action_id,
        recovery_case_id=CASE_ID,
        disposition=disposition,
    )


def build_session_factory(
    *,
    action_ids: tuple[UUID, ...] = (),
) -> MagicMock:
    scalar_result = MagicMock()
    scalar_result.all.return_value = list(action_ids)

    query_result = MagicMock()
    query_result.scalars.return_value = scalar_result

    session = MagicMock()
    session.execute = AsyncMock(
        return_value=query_result,
    )

    context = MagicMock()
    context.__aenter__ = AsyncMock(
        return_value=session,
    )
    context.__aexit__ = AsyncMock(
        return_value=False,
    )

    session_factory = MagicMock()
    session_factory.return_value = context

    return session_factory


@pytest.mark.asyncio
async def test_discovery_rejects_naive_reference_time() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        await discover_recovery_message_action_ids(
            MagicMock(),
            reference_time=datetime(2026, 8, 25, 12, 0),
            batch_size=25,
        )


@pytest.mark.asyncio
async def test_discovery_rejects_nonpositive_batch_size() -> None:
    with pytest.raises(
        ValueError,
        match="must be positive",
    ):
        await discover_recovery_message_action_ids(
            MagicMock(),
            reference_time=NOW,
            batch_size=0,
        )


@pytest.mark.asyncio
async def test_discovery_returns_due_message_action_ids() -> None:
    session_factory = build_session_factory(
        action_ids=(
            ACTION_ID_ONE,
            ACTION_ID_TWO,
        ),
    )

    action_ids = await discover_recovery_message_action_ids(
        session_factory,
        reference_time=NOW,
        batch_size=25,
    )

    assert action_ids == (
        ACTION_ID_ONE,
        ACTION_ID_TWO,
    )


@pytest.mark.asyncio
async def test_empty_batch_returns_zero_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discover = AsyncMock(
        return_value=(),
    )
    execute = AsyncMock()

    monkeypatch.setattr(
        recovery_message_batch,
        "discover_recovery_message_action_ids",
        discover,
    )
    monkeypatch.setattr(
        recovery_message_batch,
        "execute_recovery_message_action",
        execute,
    )

    result = await run_recovery_message_batch(
        MagicMock(),
        customer_provider=MagicMock(),
        notification_provider=MagicMock(),
        reference_time=NOW,
        batch_size=25,
    )

    assert result == RecoveryMessageBatchResult(
        discovered=0,
        succeeded=0,
        already_succeeded=0,
        policy_denied=0,
        retryable_failures=0,
        permanent_failures=0,
        skipped=0,
    )
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_counts_success_duplicate_and_policy_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_batch,
        "discover_recovery_message_action_ids",
        AsyncMock(
            return_value=(
                ACTION_ID_ONE,
                ACTION_ID_TWO,
                ACTION_ID_THREE,
            ),
        ),
    )

    execute = AsyncMock(
        side_effect=(
            build_execution_result(
                RecoveryActionExecutionDisposition.SUCCEEDED,
                action_id=ACTION_ID_ONE,
            ),
            build_execution_result(
                RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED,
                action_id=ACTION_ID_TWO,
            ),
            build_execution_result(
                RecoveryActionExecutionDisposition.POLICY_STOPPED,
                action_id=ACTION_ID_THREE,
            ),
        ),
    )
    monkeypatch.setattr(
        recovery_message_batch,
        "execute_recovery_message_action",
        execute,
    )

    customer_provider = MagicMock()
    notification_provider = MagicMock()

    result = await run_recovery_message_batch(
        MagicMock(),
        customer_provider=customer_provider,
        notification_provider=notification_provider,
        reference_time=NOW,
        batch_size=25,
    )

    assert result.discovered == 3
    assert result.succeeded == 1
    assert result.already_succeeded == 1
    assert result.policy_denied == 1
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    assert result.skipped == 0
    assert result.failures == ()

    assert execute.await_count == 3
    assert execute.await_args_list[0].kwargs["action_id"] == ACTION_ID_ONE
    assert execute.await_args_list[1].kwargs["action_id"] == ACTION_ID_TWO
    assert execute.await_args_list[2].kwargs["action_id"] == ACTION_ID_THREE

    for call in execute.await_args_list:
        assert call.kwargs["customer_provider"] is customer_provider
        assert call.kwargs["notification_provider"] is notification_provider
        assert call.kwargs["executed_at"] == NOW


@pytest.mark.asyncio
async def test_batch_records_retryable_and_permanent_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_batch,
        "discover_recovery_message_action_ids",
        AsyncMock(
            return_value=(
                ACTION_ID_ONE,
                ACTION_ID_TWO,
            ),
        ),
    )

    monkeypatch.setattr(
        recovery_message_batch,
        "execute_recovery_message_action",
        AsyncMock(
            side_effect=(
                RecoveryMessageProviderFailure(
                    "Customer lookup failed",
                    retryable=True,
                    status_code=503,
                ),
                RecoveryMessageProviderFailure(
                    "Delivery attempt is uncertain",
                    retryable=False,
                    status_code=503,
                ),
            ),
        ),
    )

    result = await run_recovery_message_batch(
        MagicMock(),
        customer_provider=MagicMock(),
        notification_provider=MagicMock(),
        reference_time=NOW,
        batch_size=25,
    )

    assert result.discovered == 2
    assert result.succeeded == 0
    assert result.retryable_failures == 1
    assert result.permanent_failures == 1
    assert result.skipped == 0

    assert result.failures[0].action_id == ACTION_ID_ONE
    assert result.failures[0].retryable is True

    assert result.failures[1].action_id == ACTION_ID_TWO
    assert result.failures[1].retryable is False


@pytest.mark.asyncio
async def test_batch_skips_action_that_is_no_longer_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_batch,
        "discover_recovery_message_action_ids",
        AsyncMock(
            return_value=(ACTION_ID_ONE,),
        ),
    )

    monkeypatch.setattr(
        recovery_message_batch,
        "execute_recovery_message_action",
        AsyncMock(
            side_effect=RecoveryActionNotDueError(
                "Action is not due",
            ),
        ),
    )

    result = await run_recovery_message_batch(
        MagicMock(),
        customer_provider=MagicMock(),
        notification_provider=MagicMock(),
        reference_time=NOW,
        batch_size=25,
    )

    assert result.discovered == 1
    assert result.skipped == 1
    assert result.succeeded == 0
    assert result.failures == ()


@pytest.mark.asyncio
async def test_batch_passes_execution_limits_to_each_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_message_batch,
        "discover_recovery_message_action_ids",
        AsyncMock(
            return_value=(ACTION_ID_ONE,),
        ),
    )

    execute = AsyncMock(
        return_value=build_execution_result(
            RecoveryActionExecutionDisposition.SUCCEEDED,
        ),
    )
    monkeypatch.setattr(
        recovery_message_batch,
        "execute_recovery_message_action",
        execute,
    )

    claim_timeout = timedelta(seconds=90)

    await run_recovery_message_batch(
        MagicMock(),
        customer_provider=MagicMock(),
        notification_provider=MagicMock(),
        reference_time=NOW,
        batch_size=10,
        claim_timeout=claim_timeout,
        maximum_attempts=2,
    )

    assert execute.await_args.kwargs["claim_timeout"] == claim_timeout
    assert execute.await_args.kwargs["maximum_attempts"] == 2
