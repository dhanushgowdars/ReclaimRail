import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkStatus,
)
from app.services import recovery_compensation_batch
from app.services.recovery_compensation_batch import (
    RecoveryCompensationBatchResult,
    discover_compensatable_recovery_case_ids,
    run_recovery_compensation_batch,
)
from app.services.recovery_compensation_service import (
    RecoveryCompensationDisposition,
    RecoveryCompensationNotRequiredError,
    RecoveryCompensationProviderFailure,
    RecoveryCompensationResult,
)

NOW = datetime(
    2026,
    8,
    25,
    20,
    0,
    tzinfo=UTC,
)

CASE_ONE = UUID(
    "93000000-0000-0000-0000-000000000001",
)
CASE_TWO = UUID(
    "93000000-0000-0000-0000-000000000002",
)
CASE_THREE = UUID(
    "93000000-0000-0000-0000-000000000003",
)
CASE_FOUR = UUID(
    "93000000-0000-0000-0000-000000000004",
)
CASE_FIVE = UUID(
    "93000000-0000-0000-0000-000000000005",
)


def discovery_result(
    case_ids: tuple[UUID, ...],
) -> MagicMock:
    result = MagicMock()

    result.scalars.return_value.all.return_value = list(case_ids)

    return result


def compensation_result(
    recovery_case_id: UUID,
    disposition: RecoveryCompensationDisposition,
) -> RecoveryCompensationResult:
    return RecoveryCompensationResult(
        recovery_case_id=recovery_case_id,
        disposition=disposition,
        payment_link_id=(f"plink_{recovery_case_id.hex}"),
        provider_status=(RazorpayPaymentLinkStatus.CANCELLED),
    )


@pytest.mark.asyncio
async def test_discovers_compensatable_recovery_cases() -> None:
    session = AsyncMock(
        spec=AsyncSession,
    )

    session.execute.return_value = discovery_result(
        (
            CASE_ONE,
            CASE_TWO,
        ),
    )

    result = await discover_compensatable_recovery_case_ids(
        session,
        reference_time=NOW,
        batch_size=25,
    )

    assert result == (
        CASE_ONE,
        CASE_TWO,
    )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejects_invalid_discovery_inputs() -> None:
    session = AsyncMock(
        spec=AsyncSession,
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        await discover_compensatable_recovery_case_ids(
            session,
            reference_time=datetime(
                2026,
                8,
                25,
                20,
                0,
            ),
            batch_size=25,
        )

    with pytest.raises(
        ValueError,
        match="between 1 and 100",
    ):
        await discover_compensatable_recovery_case_ids(
            session,
            reference_time=NOW,
            batch_size=0,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_classifies_all_compensation_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )

    discovery_session = AsyncMock(
        spec=AsyncSession,
    )

    session_context = AsyncMock()
    session_context.__aenter__.return_value = discovery_session

    session_factory = MagicMock(
        return_value=session_context,
    )

    discover = AsyncMock(
        return_value=(
            CASE_ONE,
            CASE_TWO,
            CASE_THREE,
            CASE_FOUR,
            CASE_FIVE,
        ),
    )

    compensate = AsyncMock(
        side_effect=[
            compensation_result(
                CASE_ONE,
                RecoveryCompensationDisposition.CANCELLED,
            ),
            compensation_result(
                CASE_TWO,
                RecoveryCompensationDisposition.ALREADY_CANCELLED,
            ),
            compensation_result(
                CASE_THREE,
                RecoveryCompensationDisposition.ESCALATED,
            ),
            RecoveryCompensationProviderFailure(
                "provider unavailable",
                retryable=True,
                status_code=503,
            ),
            RecoveryCompensationNotRequiredError(
                "not required",
            ),
        ],
    )

    monkeypatch.setattr(
        recovery_compensation_batch,
        ("discover_compensatable_recovery_case_ids"),
        discover,
    )

    monkeypatch.setattr(
        recovery_compensation_batch,
        "compensate_late_authorized_recovery",
        compensate,
    )

    result = await run_recovery_compensation_batch(
        session_factory,
        provider=provider,
        reference_time=NOW,
        batch_size=5,
    )

    assert result.discovered == 5
    assert result.cancelled == 1
    assert result.already_cancelled == 1
    assert result.escalated == 1
    assert result.retryable_failures == 1
    assert result.permanent_failures == 0
    assert result.skipped == 1

    discover.assert_awaited_once_with(
        discovery_session,
        reference_time=NOW,
        batch_size=5,
    )

    assert compensate.await_count == 5


@pytest.mark.asyncio
async def test_batch_classifies_unexpected_failure_as_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery_session = AsyncMock(
        spec=AsyncSession,
    )

    session_context = AsyncMock()
    session_context.__aenter__.return_value = discovery_session

    session_factory = MagicMock(
        return_value=session_context,
    )

    monkeypatch.setattr(
        recovery_compensation_batch,
        ("discover_compensatable_recovery_case_ids"),
        AsyncMock(
            return_value=(CASE_ONE,),
        ),
    )

    monkeypatch.setattr(
        recovery_compensation_batch,
        "compensate_late_authorized_recovery",
        AsyncMock(
            side_effect=RuntimeError(
                "unexpected",
            ),
        ),
    )

    result = await run_recovery_compensation_batch(
        session_factory,
        provider=MagicMock(
            spec=RazorpayPaymentLinkProvider,
        ),
        reference_time=NOW,
    )

    assert result.permanent_failures == 1
    assert result.failures[0].error_type == "RuntimeError"


@pytest.mark.asyncio
async def test_batch_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery_session = AsyncMock(
        spec=AsyncSession,
    )

    session_context = AsyncMock()
    session_context.__aenter__.return_value = discovery_session

    session_factory = MagicMock(
        return_value=session_context,
    )

    monkeypatch.setattr(
        recovery_compensation_batch,
        ("discover_compensatable_recovery_case_ids"),
        AsyncMock(
            return_value=(CASE_ONE,),
        ),
    )

    monkeypatch.setattr(
        recovery_compensation_batch,
        "compensate_late_authorized_recovery",
        AsyncMock(
            side_effect=(asyncio.CancelledError()),
        ),
    )

    with pytest.raises(
        asyncio.CancelledError,
    ):
        await run_recovery_compensation_batch(
            session_factory,
            provider=MagicMock(
                spec=(RazorpayPaymentLinkProvider),
            ),
            reference_time=NOW,
        )


def test_empty_batch_result_counts_are_zero() -> None:
    result = RecoveryCompensationBatchResult(
        discovered_case_ids=(),
        compensation_results=(),
        failures=(),
        skipped_case_ids=(),
    )

    assert result.discovered == 0
    assert result.cancelled == 0
    assert result.already_cancelled == 0
    assert result.escalated == 0
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    assert result.skipped == 0
