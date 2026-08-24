import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.core.cache import check_redis
from app.core.config import Settings, get_settings
from app.core.database import check_database

SettingsDependency = Annotated[Settings, Depends(get_settings)]
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
