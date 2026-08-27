import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.webhooks import router as webhook_router
from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.database import close_database


@asynccontextmanager
async def webhook_lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await asyncio.gather(
            close_database(),
            close_redis(),
        )


def create_webhook_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=f"{settings.app_name} Webhook Ingress",
        version=settings.app_version,
        description="Signature-verified Razorpay webhook ingress.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=webhook_lifespan,
    )
    application.include_router(webhook_router)
    return application


app = create_webhook_app()
