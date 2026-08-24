import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import incident_detection_batch
from app.services.incident_detection_batch import (
    normalize_payment_methods,
    run_incident_detection_batch,
)
from app.services.incident_detection_runner import (
    IncidentDetectionRunResult,
)

REFERENCE_TIME = datetime(
    2026,
    8,
    24,
    12,
    0,
    tzinfo=UTC,
)


def create_session_factory() -> tuple[
    MagicMock,
    MagicMock,
]:
    session = MagicMock(spec=AsyncSession)

    transaction_context = MagicMock()
    transaction_context.__aenter__ = AsyncMock(
        return_value=None,
    )
    transaction_context.__aexit__ = AsyncMock(
        return_value=None,
    )
    session.begin.return_value = transaction_context

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(
        return_value=session,
    )
    session_context.__aexit__ = AsyncMock(
        return_value=None,
    )

    session_factory = MagicMock(
        return_value=session_context,
    )

    return session_factory, session


def test_normalizes_and_deduplicates_payment_methods() -> None:
    result = normalize_payment_methods(
        [
            " UPI ",
            "card",
            "upi",
            " CARD ",
            "netbanking",
        ],
    )

    assert result == (
        "upi",
        "card",
        "netbanking",
    )


def test_rejects_empty_payment_method_configuration() -> None:
    with pytest.raises(
        ValueError,
        match="At least one",
    ):
        normalize_payment_methods([])

    with pytest.raises(
        ValueError,
        match="empty values",
    ):
        normalize_payment_methods(["upi", " "])


@pytest.mark.asyncio
async def test_isolates_method_failures_and_shares_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, session = create_session_factory()

    upi_result = MagicMock(
        spec=IncidentDetectionRunResult,
    )

    run_detection = AsyncMock(
        side_effect=[
            upi_result,
            RuntimeError("card history unavailable"),
        ],
    )

    monkeypatch.setattr(
        incident_detection_batch,
        "run_payment_method_incident_detection",
        run_detection,
    )

    detector_run_id = uuid4()

    result = await run_incident_detection_batch(
        session_factory,
        payment_methods=[
            " UPI ",
            "card",
            "upi",
        ],
        currency="inr",
        reference_time=REFERENCE_TIME,
        detector_run_id=detector_run_id,
    )

    assert result.detector_run_id == detector_run_id
    assert result.currency == "INR"
    assert result.attempted == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.successful_results == (upi_result,)

    failure = result.failures[0]
    assert failure.payment_method == "card"
    assert failure.error_type == "RuntimeError"
    assert failure.error_message == ("card history unavailable")

    assert session_factory.call_count == 2
    assert run_detection.await_count == 2

    first_call = run_detection.await_args_list[0]
    second_call = run_detection.await_args_list[1]

    assert first_call.args[0] is session
    assert second_call.args[0] is session

    assert first_call.kwargs["payment_method"] == "upi"
    assert second_call.kwargs["payment_method"] == "card"

    assert first_call.kwargs["detector_run_id"] == detector_run_id
    assert second_call.kwargs["detector_run_id"] == detector_run_id


@pytest.mark.asyncio
async def test_propagates_worker_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, _ = create_session_factory()

    run_detection = AsyncMock(
        side_effect=asyncio.CancelledError,
    )

    monkeypatch.setattr(
        incident_detection_batch,
        "run_payment_method_incident_detection",
        run_detection,
    )

    with pytest.raises(asyncio.CancelledError):
        await run_incident_detection_batch(
            session_factory,
            payment_methods=["upi"],
            currency="INR",
            reference_time=REFERENCE_TIME,
        )
