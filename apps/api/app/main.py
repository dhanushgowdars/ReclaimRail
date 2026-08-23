from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=("Incident-aware, policy-bounded payment recovery orchestrator."),
    )

    application.include_router(health_router)
    return application


app = create_app()
