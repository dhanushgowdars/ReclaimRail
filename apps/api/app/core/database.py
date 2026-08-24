from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


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


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_database_engine(),
            expire_on_commit=False,
        )

    return _session_factory


async def get_database_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()

    async with session_factory() as session:
        yield session


async def check_database() -> None:
    async with get_database_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database() -> None:
    global _engine, _session_factory

    _session_factory = None

    if _engine is not None:
        await _engine.dispose()
        _engine = None
