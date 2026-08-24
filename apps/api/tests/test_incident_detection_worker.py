import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.incident_detection_batch import (
    IncidentDetectionBatchResult,
)
from app.workers import incident_detection_worker
from app.workers.incident_detection_worker import (
    parse_run_once,
    run_incident_detection_worker,
)

REFERENCE_TIME = datetime(
    2026,
    8,
    24,
    12,
    0,
    tzinfo=UTC,
)


def create_settings() -> SimpleNamespace:
    return SimpleNamespace(
        incident_payment_methods=(
            "upi",
            "card",
        ),
        incident_currency="INR",
        incident_window_minutes=5,
        incident_baseline_window_count=12,
        incident_poll_interval_seconds=60.0,
    )


def create_batch_result() -> IncidentDetectionBatchResult:
    return IncidentDetectionBatchResult(
        detector_run_id=uuid4(),
        reference_time=REFERENCE_TIME,
        currency="INR",
        successful_results=(),
        failures=(),
    )


def test_parse_run_once_defaults_to_continuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["incident_detection_worker"],
    )

    assert parse_run_once() is False


def test_parse_run_once_accepts_once_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "incident_detection_worker",
            "--once",
        ],
    )

    assert parse_run_once() is True


@pytest.mark.asyncio
async def test_run_once_executes_batch_and_closes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = create_settings()
    session_factory = MagicMock()

    run_batch = AsyncMock(
        return_value=create_batch_result(),
    )
    close_database = AsyncMock()

    monkeypatch.setattr(
        incident_detection_worker,
        "get_settings",
        MagicMock(return_value=settings),
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "get_session_factory",
        MagicMock(return_value=session_factory),
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "run_incident_detection_batch",
        run_batch,
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "close_database",
        close_database,
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "utc_now",
        MagicMock(return_value=REFERENCE_TIME),
    )

    await run_incident_detection_worker(
        run_once=True,
    )

    run_batch.assert_awaited_once_with(
        session_factory,
        payment_methods=("upi", "card"),
        currency="INR",
        reference_time=REFERENCE_TIME,
        window_size=incident_detection_worker.timedelta(
            minutes=5,
        ),
        baseline_window_count=12,
    )
    close_database.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_run_once_closes_database_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = create_settings()
    session_factory = MagicMock()

    run_batch = AsyncMock(
        side_effect=RuntimeError(
            "database unavailable",
        ),
    )
    close_database = AsyncMock()

    monkeypatch.setattr(
        incident_detection_worker,
        "get_settings",
        MagicMock(return_value=settings),
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "get_session_factory",
        MagicMock(return_value=session_factory),
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "run_incident_detection_batch",
        run_batch,
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "close_database",
        close_database,
    )
    monkeypatch.setattr(
        incident_detection_worker,
        "utc_now",
        MagicMock(return_value=REFERENCE_TIME),
    )

    with pytest.raises(
        RuntimeError,
        match="database unavailable",
    ):
        await run_incident_detection_worker(
            run_once=True,
        )

    close_database.assert_awaited_once_with()
