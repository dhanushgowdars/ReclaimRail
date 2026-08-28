import asyncio
import json
import logging
import os
import socket
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from redis.asyncio import Redis

from app.core.cache import get_redis_client
from app.core.config import Settings
from app.services.payment_lab_live_run_service import PaymentLabLiveBusinessState

LOGGER = logging.getLogger("reclaimrail.worker-supervision")
HEARTBEAT_KEY_PREFIX = "reclaimrail:worker-heartbeat:v1"


class WorkerName(StrEnum):
    OUTBOX = "outbox"
    PAYMENT_CONSUMER = "payment_consumer"
    PAYMENT_LAB_RECOVERY = "payment_lab_recovery"
    RECOVERY_ACTION = "recovery_action"
    RECOVERY_COMPENSATION = "recovery_compensation"
    RECOVERY_MESSAGE = "recovery_message"
    RECOVERY_OUTCOME = "recovery_outcome"
    INCIDENT_DETECTION = "incident_detection"


EXPECTED_WORKERS = tuple(WorkerName)

LIVE_RUN_WORKER_RESPONSIBILITY = {
    PaymentLabLiveBusinessState.FAILURE_STABILIZING: WorkerName.PAYMENT_LAB_RECOVERY,
    PaymentLabLiveBusinessState.DIAGNOSING: WorkerName.PAYMENT_LAB_RECOVERY,
    PaymentLabLiveBusinessState.AWAITING_POLICY: WorkerName.PAYMENT_LAB_RECOVERY,
    PaymentLabLiveBusinessState.EXECUTING_ACTION: WorkerName.RECOVERY_ACTION,
    PaymentLabLiveBusinessState.AWAITING_RECOVERY_PAYMENT: WorkerName.RECOVERY_OUTCOME,
    PaymentLabLiveBusinessState.STOPPING_RECOVERY: WorkerName.RECOVERY_COMPENSATION,
}


class WorkerReportedState(StrEnum):
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPING = "stopping"


class WorkerHealthStatus(StrEnum):
    HEALTHY = "healthy"
    STARTING = "starting"
    DELAYED = "delayed"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    DOWN = "down"


class WorkerFleetStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    name: WorkerName
    status: WorkerHealthStatus
    instance_id: str | None
    heartbeat_age_seconds: float | None
    started_at: datetime | None
    last_heartbeat_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    last_error_type: str | None
    metrics: dict[str, int | float | str | bool | None]


@dataclass(frozen=True, slots=True)
class WorkerFleetHealth:
    status: WorkerFleetStatus
    workers: tuple[WorkerHealth, ...]
    healthy_count: int
    expected_count: int
    generated_at: datetime


def heartbeat_key(worker_name: WorkerName) -> str:
    return f"{HEARTBEAT_KEY_PREFIX}:{worker_name.value}"


def responsible_worker_for_live_state(
    business_state: PaymentLabLiveBusinessState,
) -> WorkerName | None:
    return LIVE_RUN_WORKER_RESPONSIBILITY.get(business_state)


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_worker_instance_id(worker_name: WorkerName) -> str:
    hostname = socket.gethostname().strip() or "unknown-host"
    return f"{worker_name.value}:{hostname}:{os.getpid()}"


class NoopWorkerHeartbeatReporter:
    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        await self.stop()

    async def start(self) -> Self:
        return self

    async def stop(self) -> None:
        return None

    async def record_success(
        self,
        metrics: Mapping[str, int | float | str | bool | None] | None = None,
    ) -> None:
        return None

    async def record_failure(self, error: BaseException) -> None:
        return None


class WorkerHeartbeatReporter:
    def __init__(
        self,
        redis_client: Redis,
        *,
        worker_name: WorkerName,
        heartbeat_interval_seconds: float,
        heartbeat_ttl_seconds: int,
        degraded_failure_threshold: int,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if heartbeat_ttl_seconds <= heartbeat_interval_seconds * 2:
            raise ValueError("Worker heartbeat TTL must exceed two heartbeat intervals")

        self._redis_client = redis_client
        self._worker_name = worker_name
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self._degraded_failure_threshold = degraded_failure_threshold
        self._now = now
        self._instance_id = build_worker_instance_id(worker_name)
        self._started_at: datetime | None = None
        self._last_heartbeat_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_error_type: str | None = None
        self._consecutive_failures = 0
        self._state = WorkerReportedState.STARTING
        self._metrics: dict[str, int | float | str | bool | None] = {}
        self._pulse_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        return await self.start()

    async def start(self) -> Self:
        self._started_at = self._now()
        await self._safe_publish()
        self._pulse_task = asyncio.create_task(
            self._pulse(),
            name=f"worker-heartbeat:{self._worker_name.value}",
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        if exc_value is not None and not isinstance(exc_value, asyncio.CancelledError):
            await self.record_failure(exc_value)

        await self.stop()

    async def stop(self) -> None:

        if self._pulse_task is not None:
            self._pulse_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._pulse_task

        self._state = WorkerReportedState.STOPPING
        await self._safe_publish()

    async def record_success(
        self,
        metrics: Mapping[str, int | float | str | bool | None] | None = None,
    ) -> None:
        async with self._lock:
            self._state = WorkerReportedState.HEALTHY
            self._last_success_at = self._now()
            self._last_error_type = None
            self._consecutive_failures = 0
            self._metrics = dict(metrics or {})
            await self._safe_publish()

    async def record_failure(self, error: BaseException) -> None:
        async with self._lock:
            self._last_failure_at = self._now()
            self._last_error_type = type(error).__name__
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._degraded_failure_threshold:
                self._state = WorkerReportedState.DEGRADED
            await self._safe_publish()

    async def _pulse(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            async with self._lock:
                await self._safe_publish()

    async def _safe_publish(self) -> None:
        try:
            await self._publish()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOGGER.warning(
                "Worker heartbeat publish failed: worker=%s error_type=%s",
                self._worker_name.value,
                type(error).__name__,
            )

    async def _publish(self) -> None:
        heartbeat_at = self._now()
        self._last_heartbeat_at = heartbeat_at
        payload = json.dumps(
            {
                "schema_version": 1,
                "worker_name": self._worker_name.value,
                "instance_id": self._instance_id,
                "state": self._state.value,
                "started_at": (
                    self._started_at.isoformat() if self._started_at is not None else None
                ),
                "last_heartbeat_at": heartbeat_at.isoformat(),
                "last_success_at": (
                    self._last_success_at.isoformat() if self._last_success_at is not None else None
                ),
                "last_failure_at": (
                    self._last_failure_at.isoformat() if self._last_failure_at is not None else None
                ),
                "consecutive_failures": self._consecutive_failures,
                "last_error_type": self._last_error_type,
                "metrics": self._metrics,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        await self._redis_client.set(
            heartbeat_key(self._worker_name),
            payload,
            ex=self._heartbeat_ttl_seconds,
        )


def create_worker_heartbeat_reporter(
    settings: Settings,
    *,
    worker_name: WorkerName,
    redis_client: Redis | None = None,
) -> WorkerHeartbeatReporter | NoopWorkerHeartbeatReporter:
    redis_url = getattr(settings, "redis_url", None)
    if redis_url is None or not redis_url.get_secret_value():
        return NoopWorkerHeartbeatReporter()

    return WorkerHeartbeatReporter(
        redis_client or get_redis_client(),
        worker_name=worker_name,
        heartbeat_interval_seconds=settings.worker_heartbeat_interval_seconds,
        heartbeat_ttl_seconds=settings.worker_heartbeat_ttl_seconds,
        degraded_failure_threshold=settings.worker_degraded_failure_threshold,
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _down_worker(worker_name: WorkerName) -> WorkerHealth:
    return WorkerHealth(
        name=worker_name,
        status=WorkerHealthStatus.DOWN,
        instance_id=None,
        heartbeat_age_seconds=None,
        started_at=None,
        last_heartbeat_at=None,
        last_success_at=None,
        last_failure_at=None,
        consecutive_failures=0,
        last_error_type=None,
        metrics={},
    )


def parse_worker_health(
    worker_name: WorkerName,
    raw_payload: str | bytes | None,
    *,
    reference_time: datetime,
    delayed_after_seconds: float,
) -> WorkerHealth:
    if raw_payload is None:
        return _down_worker(worker_name)

    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return _down_worker(worker_name)
    if not isinstance(payload, dict) or payload.get("worker_name") != worker_name.value:
        return _down_worker(worker_name)

    last_heartbeat_at = _parse_datetime(payload.get("last_heartbeat_at"))
    if last_heartbeat_at is None:
        return _down_worker(worker_name)

    heartbeat_age_seconds = max(
        0.0,
        (reference_time - last_heartbeat_at).total_seconds(),
    )
    raw_state = payload.get("state")
    if not isinstance(raw_state, str):
        return _down_worker(worker_name)
    try:
        reported_state = WorkerReportedState(raw_state)
    except ValueError:
        return _down_worker(worker_name)

    if heartbeat_age_seconds > delayed_after_seconds:
        health_status = WorkerHealthStatus.DELAYED
    elif reported_state is WorkerReportedState.DEGRADED:
        health_status = WorkerHealthStatus.DEGRADED
    elif reported_state is WorkerReportedState.STARTING:
        health_status = WorkerHealthStatus.STARTING
    elif reported_state is WorkerReportedState.STOPPING:
        health_status = WorkerHealthStatus.STOPPING
    else:
        health_status = WorkerHealthStatus.HEALTHY

    consecutive_failures = payload.get("consecutive_failures", 0)
    if not isinstance(consecutive_failures, int) or consecutive_failures < 0:
        consecutive_failures = 0

    raw_metrics = payload.get("metrics")
    metrics: dict[str, int | float | str | bool | None] = {}
    if isinstance(raw_metrics, dict):
        for key, value in raw_metrics.items():
            if isinstance(key, str) and (
                value is None or isinstance(value, (int, float, str, bool))
            ):
                metrics[key] = value

    return WorkerHealth(
        name=worker_name,
        status=health_status,
        instance_id=(
            payload.get("instance_id") if isinstance(payload.get("instance_id"), str) else None
        ),
        heartbeat_age_seconds=round(heartbeat_age_seconds, 2),
        started_at=_parse_datetime(payload.get("started_at")),
        last_heartbeat_at=last_heartbeat_at,
        last_success_at=_parse_datetime(payload.get("last_success_at")),
        last_failure_at=_parse_datetime(payload.get("last_failure_at")),
        consecutive_failures=consecutive_failures,
        last_error_type=(
            payload.get("last_error_type")
            if isinstance(payload.get("last_error_type"), str)
            else None
        ),
        metrics=metrics,
    )


async def load_worker_fleet_health(
    redis_client: Redis,
    *,
    reference_time: datetime,
    delayed_after_seconds: float,
) -> WorkerFleetHealth:
    raw_heartbeats = await redis_client.mget(
        [heartbeat_key(worker_name) for worker_name in EXPECTED_WORKERS],
    )
    workers = tuple(
        parse_worker_health(
            worker_name,
            raw_payload,
            reference_time=reference_time,
            delayed_after_seconds=delayed_after_seconds,
        )
        for worker_name, raw_payload in zip(EXPECTED_WORKERS, raw_heartbeats, strict=True)
    )
    healthy_count = sum(worker.status is WorkerHealthStatus.HEALTHY for worker in workers)
    fleet_status = (
        WorkerFleetStatus.HEALTHY
        if healthy_count == len(EXPECTED_WORKERS)
        else WorkerFleetStatus.DEGRADED
    )
    return WorkerFleetHealth(
        status=fleet_status,
        workers=workers,
        healthy_count=healthy_count,
        expected_count=len(EXPECTED_WORKERS),
        generated_at=reference_time,
    )
