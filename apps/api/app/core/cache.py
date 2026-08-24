from redis.asyncio import Redis

from app.core.config import get_settings

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global _redis_client

    if _redis_client is None:
        redis_url = get_settings().redis_url

        if redis_url is None or not redis_url.get_secret_value():
            raise RuntimeError("Redis URL is not configured")

        _redis_client = Redis.from_url(
            redis_url.get_secret_value(),
            decode_responses=True,
        )

    return _redis_client


async def check_redis() -> None:
    pong = await get_redis_client().ping()

    if not pong:
        raise ConnectionError("Redis ping failed")


async def close_redis() -> None:
    global _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
