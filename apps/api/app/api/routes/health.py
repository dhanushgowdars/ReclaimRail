import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import check_redis, get_redis_client
from app.core.config import Settings, get_settings
from app.core.database import check_database, get_database_session
from app.services.operational_queue_service import (
    DatabaseQueueMetric,
    load_operational_queue_diagnostics,
)
from app.services.worker_supervision_service import (
    EXPECTED_WORKERS,
    WorkerHealth,
    load_worker_fleet_health,
)

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[AsyncSession, Depends(get_database_session)]
DependencyCheck = Callable[[], Awaitable[None]]

router = APIRouter(prefix="/health", tags=["health"])


class LiveHealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class DependencyHealth(BaseModel):
    status: Literal["up", "down"]
    latency_ms: float = Field(ge=0)


class ReadinessHealthResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyHealth]


class WorkerHealthResponse(BaseModel):
    name: str
    status: str
    instance_id: str | None
    heartbeat_age_seconds: float | None = Field(default=None, ge=0)
    started_at: datetime | None
    last_heartbeat_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int = Field(ge=0)
    last_error_type: str | None
    metrics: dict[str, int | float | str | bool | None]


class WorkerFleetHealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unavailable"]
    healthy_count: int = Field(ge=0)
    expected_count: int = Field(ge=1)
    generated_at: datetime
    workers: list[WorkerHealthResponse]


class DatabaseQueueMetricResponse(BaseModel):
    name: str
    pending_count: int = Field(ge=0)
    oldest_age_seconds: float | None = Field(default=None, ge=0)


class OperationalQueueHealthResponse(BaseModel):
    status: Literal["healthy", "attention_required", "unavailable"]
    database_queues: list[DatabaseQueueMetricResponse]
    webhook_stream_depth: int = Field(ge=0)
    payment_consumer_pending: int = Field(ge=0)
    dead_letter_depth: int = Field(ge=0)
    generated_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_worker_health_response(worker: WorkerHealth) -> WorkerHealthResponse:
    return WorkerHealthResponse(
        name=worker.name.value,
        status=worker.status.value,
        instance_id=worker.instance_id,
        heartbeat_age_seconds=worker.heartbeat_age_seconds,
        started_at=worker.started_at,
        last_heartbeat_at=worker.last_heartbeat_at,
        last_success_at=worker.last_success_at,
        last_failure_at=worker.last_failure_at,
        consecutive_failures=worker.consecutive_failures,
        last_error_type=worker.last_error_type,
        metrics=worker.metrics,
    )


def to_database_queue_metric_response(
    metric: DatabaseQueueMetric,
) -> DatabaseQueueMetricResponse:
    return DatabaseQueueMetricResponse(
        name=metric.name,
        pending_count=metric.pending_count,
        oldest_age_seconds=metric.oldest_age_seconds,
    )


async def run_dependency_check(check: DependencyCheck) -> DependencyHealth:
    started_at = perf_counter()

    try:
        await check()
        dependency_status: Literal["up", "down"] = "up"
    except Exception:
        dependency_status = "down"

    latency_ms = round((perf_counter() - started_at) * 1000, 2)

    return DependencyHealth(
        status=dependency_status,
        latency_ms=latency_ms,
    )


@router.get(
    "/live",
    response_model=LiveHealthResponse,
    summary="Check API process liveness",
)
async def live_health(
    settings: SettingsDependency,
) -> LiveHealthResponse:
    return LiveHealthResponse(
        status="ok",
        service="reclaimrail-api",
        version=settings.app_version,
    )


@router.get(
    "/ready",
    response_model=ReadinessHealthResponse,
    summary="Check API dependency readiness",
)
async def ready_health(response: Response) -> ReadinessHealthResponse:
    database_health, redis_health = await asyncio.gather(
        run_dependency_check(check_database),
        run_dependency_check(check_redis),
    )

    checks = {
        "database": database_health,
        "redis": redis_health,
    }

    is_ready = all(check.status == "up" for check in checks.values())

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessHealthResponse(
        status="ready" if is_ready else "not_ready",
        checks=checks,
    )


@router.get(
    "/workers",
    response_model=WorkerFleetHealthResponse,
    summary="Inspect required recovery worker health",
)
async def worker_health(
    response: Response,
    settings: SettingsDependency,
) -> WorkerFleetHealthResponse:
    reference_time = utc_now()
    try:
        fleet = await load_worker_fleet_health(
            get_redis_client(),
            reference_time=reference_time,
            delayed_after_seconds=settings.worker_delayed_after_seconds,
        )
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return WorkerFleetHealthResponse(
            status="unavailable",
            healthy_count=0,
            expected_count=len(EXPECTED_WORKERS),
            generated_at=reference_time,
            workers=[],
        )

    return WorkerFleetHealthResponse(
        status=fleet.status.value,
        healthy_count=fleet.healthy_count,
        expected_count=fleet.expected_count,
        generated_at=fleet.generated_at,
        workers=[to_worker_health_response(worker) for worker in fleet.workers],
    )


@router.get(
    "/queues",
    response_model=OperationalQueueHealthResponse,
    summary="Inspect recovery queue depth and age",
)
async def queue_health(
    response: Response,
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
) -> OperationalQueueHealthResponse:
    reference_time = utc_now()
    try:
        diagnostics = await load_operational_queue_diagnostics(
            session,
            get_redis_client(),
            settings=settings,
            reference_time=reference_time,
        )
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return OperationalQueueHealthResponse(
            status="unavailable",
            database_queues=[],
            webhook_stream_depth=0,
            payment_consumer_pending=0,
            dead_letter_depth=0,
            generated_at=reference_time,
        )

    return OperationalQueueHealthResponse(
        status=diagnostics.status.value,
        database_queues=[
            to_database_queue_metric_response(metric) for metric in diagnostics.database_queues
        ],
        webhook_stream_depth=diagnostics.webhook_stream_depth,
        payment_consumer_pending=diagnostics.payment_consumer_pending,
        dead_letter_depth=diagnostics.dead_letter_depth,
        generated_at=diagnostics.generated_at,
    )
