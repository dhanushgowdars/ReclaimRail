from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.integrations.razorpay.orders import (
    RazorpayOrderPayment,
    RazorpayOrderPaymentStatus,
    RazorpayOrderProviderError,
    RazorpayProviderFailureKind,
)
from app.integrations.razorpay.payment_events import normalize_razorpay_payment_event
from app.integrations.razorpay.webhooks import RazorpayWebhookEnvelope
from app.services import payment_truth_reconciliation
from app.services.payment_truth_reconciliation import reconcile_payment_truth_batch

NOW = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)
ATTEMPTS = tuple(UUID(f"90000000-0000-0000-0000-00000000000{index}") for index in range(1, 6))


class SessionContext:
    async def __aenter__(self) -> AsyncMock:
        return AsyncMock()

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.fixture(autouse=True)
def stub_control_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        payment_truth_reconciliation,
        "_control_counts",
        AsyncMock(
            return_value=(
                payment_truth_reconciliation.PaymentTruthReconciliationControlCounts(
                    cooling_down=0,
                    open_circuits=0,
                    exhausted=0,
                    synthetic_blocked=0,
                )
            ),
        ),
    )


def test_retry_delay_is_exponential_and_bounded() -> None:
    assert payment_truth_reconciliation._retry_delay(  # noqa: SLF001
        failure_count=1,
        base_delay=timedelta(seconds=15),
        maximum_delay=timedelta(minutes=5),
    ) == timedelta(seconds=15)
    assert payment_truth_reconciliation._retry_delay(  # noqa: SLF001
        failure_count=4,
        base_delay=timedelta(seconds=15),
        maximum_delay=timedelta(minutes=5),
    ) == timedelta(seconds=120)
    assert payment_truth_reconciliation._retry_delay(  # noqa: SLF001
        failure_count=20,
        base_delay=timedelta(seconds=15),
        maximum_delay=timedelta(minutes=5),
    ) == timedelta(minutes=5)


def test_unavailable_evidence_identity_does_not_contain_observation_time() -> None:
    error = RazorpayOrderProviderError(
        "provider unavailable",
        retryable=True,
        status_code=503,
        kind=RazorpayProviderFailureKind.SERVER_ERROR,
    )
    fingerprint = payment_truth_reconciliation._failure_fingerprint(error)  # noqa: SLF001

    reference = payment_truth_reconciliation._unavailable_source_reference(  # noqa: SLF001
        payment_attempt_id=ATTEMPTS[0],
        payment_state_version=7,
        observation_sequence=2,
        failure_fingerprint=fingerprint,
    )

    assert NOW.isoformat() not in reference
    assert reference == payment_truth_reconciliation._unavailable_source_reference(  # noqa: SLF001
        payment_attempt_id=ATTEMPTS[0],
        payment_state_version=7,
        observation_sequence=2,
        failure_fingerprint=fingerprint,
    )


def test_provider_success_schedules_next_bounded_recheck() -> None:
    state = MagicMock()

    payment_truth_reconciliation._record_provider_success(  # noqa: SLF001
        state,
        observed_at=NOW,
    )

    assert state.attempt_count == 0
    assert state.consecutive_failures == 0
    assert state.next_retry_at == NOW + payment_truth_reconciliation.RECONCILE_AFTER
    assert state.circuit_open_until is None
    assert state.exhausted_at is None


def test_provider_payment_is_adapted_to_a_valid_canonical_event() -> None:
    payment = RazorpayOrderPayment(
        id="pay_gate1a_valid_event",
        amount=349_900,
        currency="INR",
        status=RazorpayOrderPaymentStatus.FAILED,
        order_id="order_gate1a_valid_event",
        method="netbanking",
        created_at=int(NOW.timestamp()),
        error_code="BAD_REQUEST_ERROR",
        error_reason="payment_failed",
    )

    event = payment_truth_reconciliation._provider_event(payment, NOW)  # noqa: SLF001
    envelope = RazorpayWebhookEnvelope.model_validate(event.payload)
    lifecycle = normalize_razorpay_payment_event(
        webhook_event_id=event.id,
        provider_event_id=event.provider_event_id,
        envelope=envelope,
    )

    assert lifecycle.payment_id == payment.payment_id
    assert lifecycle.order_id == payment.order_id
    assert lifecycle.state.value == payment.status.value


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


@pytest.mark.asyncio
async def test_deferred_candidate_does_not_consume_provider_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_truth_reconciliation,
        "_candidate_ids",
        AsyncMock(return_value=ATTEMPTS[:1]),
    )
    reconcile_one = AsyncMock(return_value="deferred")
    monkeypatch.setattr(payment_truth_reconciliation, "_reconcile_one", reconcile_one)

    result = await reconcile_payment_truth_batch(
        MagicMock(return_value=SessionContext()),
        provider=MagicMock(),
        reference_time=NOW,
        batch_size=1,
    )

    assert result.checked == 1
    assert result.deferred == 1
    assert result.provider_calls == 0
