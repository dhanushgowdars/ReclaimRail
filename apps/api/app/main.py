import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.recovery_case_detail import router as recovery_case_detail_router
from app.api.routes.recovery_dashboard import router as recovery_dashboard_router
from app.api.routes.recovery_incidents import router as recovery_incidents_router
from app.api.routes.recovery_outcomes import router as recovery_outcomes_router
from app.api.routes.webhooks import router as webhook_router
from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.database import close_database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await asyncio.gather(
            close_database(),
            close_redis(),
        )


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Incident-aware, policy-bounded payment recovery orchestrator.",
        lifespan=lifespan,
    )

    application.include_router(health_router)
    application.include_router(recovery_dashboard_router)
    application.include_router(recovery_case_detail_router)
    application.include_router(recovery_incidents_router)
    application.include_router(recovery_outcomes_router)
    application.include_router(webhook_router)

    return application


app = create_app()
