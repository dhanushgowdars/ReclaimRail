import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.worker_supervision_service import (
    EXPECTED_WORKERS,
    WorkerFleetStatus,
    WorkerHealthStatus,
    WorkerHeartbeatReporter,
    WorkerName,
    heartbeat_key,
    load_worker_fleet_health,
    parse_worker_health,
)

NOW = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)


def heartbeat_payload(
    worker_name: WorkerName,
    *,
    state: str = "healthy",
    heartbeat_at: datetime = NOW,
    consecutive_failures: int = 0,
) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "worker_name": worker_name.value,
            "instance_id": f"{worker_name.value}:test-host:42",
            "state": state,
            "started_at": (NOW - timedelta(minutes=1)).isoformat(),
            "last_heartbeat_at": heartbeat_at.isoformat(),
            "last_success_at": NOW.isoformat(),
            "last_failure_at": None,
            "consecutive_failures": consecutive_failures,
            "last_error_type": None,
            "metrics": {},
        },
    )


def test_missing_or_invalid_heartbeat_is_down() -> None:
    missing = parse_worker_health(
        WorkerName.OUTBOX,
        None,
        reference_time=NOW,
        delayed_after_seconds=15,
    )
    invalid = parse_worker_health(
        WorkerName.OUTBOX,
        "not-json",
        reference_time=NOW,
        delayed_after_seconds=15,
    )

    assert missing.status is WorkerHealthStatus.DOWN
    assert invalid.status is WorkerHealthStatus.DOWN


def test_old_heartbeat_is_delayed() -> None:
    result = parse_worker_health(
        WorkerName.RECOVERY_ACTION,
        heartbeat_payload(
            WorkerName.RECOVERY_ACTION,
            heartbeat_at=NOW - timedelta(seconds=16),
        ),
        reference_time=NOW,
        delayed_after_seconds=15,
    )

    assert result.status is WorkerHealthStatus.DELAYED
    assert result.heartbeat_age_seconds == 16


@pytest.mark.asyncio
async def test_fleet_requires_every_expected_worker_to_be_healthy() -> None:
    redis_client = AsyncMock()
    redis_client.mget.return_value = [
        heartbeat_payload(worker_name) if index == 0 else None
        for index, worker_name in enumerate(EXPECTED_WORKERS)
    ]

    result = await load_worker_fleet_health(
        redis_client,
        reference_time=NOW,
        delayed_after_seconds=15,
    )

    assert result.status is WorkerFleetStatus.DEGRADED
    assert result.healthy_count == 1
    assert result.expected_count == 8
    assert result.workers[0].status is WorkerHealthStatus.HEALTHY
    assert all(worker.status is WorkerHealthStatus.DOWN for worker in result.workers[1:])
    redis_client.mget.assert_awaited_once_with(
        [heartbeat_key(worker_name) for worker_name in EXPECTED_WORKERS],
    )


@pytest.mark.asyncio
async def test_reporter_resets_failures_after_success() -> None:
    redis_client = AsyncMock()
    reporter = WorkerHeartbeatReporter(
        redis_client,
        worker_name=WorkerName.PAYMENT_LAB_RECOVERY,
        heartbeat_interval_seconds=5,
        heartbeat_ttl_seconds=30,
        degraded_failure_threshold=1,
        now=MagicMock(return_value=NOW),
    )

    async with reporter:
        await reporter.record_failure(RuntimeError("provider unavailable"))
        await reporter.record_success({"discovered": 1})

    payload = json.loads(redis_client.set.await_args_list[-2].args[1])
    assert payload["state"] == "healthy"
    assert payload["consecutive_failures"] == 0
    assert payload["last_error_type"] is None
    assert payload["metrics"] == {"discovered": 1}
    assert redis_client.set.await_args_list[-2].kwargs == {"ex": 30}


def test_reporter_rejects_unsafe_ttl() -> None:
    with pytest.raises(ValueError, match="TTL"):
        WorkerHeartbeatReporter(
            AsyncMock(),
            worker_name=WorkerName.OUTBOX,
            heartbeat_interval_seconds=5,
            heartbeat_ttl_seconds=10,
            degraded_failure_threshold=3,
        )
