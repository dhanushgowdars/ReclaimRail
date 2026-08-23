from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/health", tags=["health"])


class LiveHealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


@router.get(
    "/live",
    response_model=LiveHealthResponse,
    summary="Check API process liveness",
)
async def live_health(
    settings: Settings = Depends(get_settings),
) -> LiveHealthResponse:
    return LiveHealthResponse(
        status="ok",
        service="reclaimrail-api",
        version=settings.app_version,
    )
