from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.integrations.razorpay.orders import (
    RazorpayOrderProviderError,
    RazorpayProviderFailureKind,
)
from app.services import payment_truth_reconciliation
from app.services.payment_truth_reconciliation import reconcile_payment_truth_batch

NOW = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)
ATTEMPTS = tuple(UUID(f"90000000-0000-0000-0000-00000000000{index}") for index in range(1, 6))


class SessionContext:
    async def __aenter__(self) -> AsyncMock:
        return AsyncMock()

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_reconciliation_opens_circuit_after_three_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_truth_reconciliation,
        "_candidate_ids",
        AsyncMock(return_value=ATTEMPTS),
    )
    unavailable = RazorpayOrderProviderError(
        "provider unavailable",
        retryable=True,
        kind=RazorpayProviderFailureKind.READ_TIMEOUT,
    )
    reconcile_one = AsyncMock(side_effect=unavailable)
    monkeypatch.setattr(payment_truth_reconciliation, "_reconcile_one", reconcile_one)
    session_factory = MagicMock(return_value=SessionContext())

    result = await reconcile_payment_truth_batch(
        session_factory,
        provider=MagicMock(),
        reference_time=NOW,
        batch_size=5,
    )

    assert result.checked == 3
    assert result.unavailable == 3
    assert result.circuit_opened is True
    assert reconcile_one.await_count == 3


@pytest.mark.asyncio
async def test_success_resets_consecutive_provider_failure_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_truth_reconciliation,
        "_candidate_ids",
        AsyncMock(return_value=ATTEMPTS),
    )
    unavailable = RazorpayOrderProviderError(
        "provider unavailable",
        retryable=True,
        kind=RazorpayProviderFailureKind.DNS_NETWORK,
    )
    reconcile_one = AsyncMock(
        side_effect=[unavailable, unavailable, "unchanged", unavailable, unavailable],
    )
    monkeypatch.setattr(payment_truth_reconciliation, "_reconcile_one", reconcile_one)

    result = await reconcile_payment_truth_batch(
        MagicMock(return_value=SessionContext()),
        provider=MagicMock(),
        reference_time=NOW,
        batch_size=5,
    )

    assert result.checked == 5
    assert result.unavailable == 4
    assert result.unchanged == 1
    assert result.circuit_opened is False
