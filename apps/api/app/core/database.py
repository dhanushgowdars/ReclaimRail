from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None


def get_database_engine() -> AsyncEngine:
    global _engine

    if _engine is None:
        database_url = get_settings().database_url

        if database_url is None or not database_url.get_secret_value():
            raise RuntimeError("Database URL is not configured")

        _engine = create_async_engine(
            database_url.get_secret_value(),
            pool_pre_ping=True,
        )

    return _engine


async def check_database() -> None:
    async with get_database_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database() -> None:
    global _engine

    if _engine is not None:
        await _engine.dispose()
        _engine = None
