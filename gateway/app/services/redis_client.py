"""
Process-wide Redis client shared by the rate limiter and health checks.

Keeping the client in a dedicated module (instead of a global on main) means
importers always see the live client, not a stale copy bound at import time.
"""
from typing import Optional

import redis.asyncio as redis

from common.app.config import settings

redis_client: Optional[redis.Redis] = None


async def connect_redis() -> redis.Redis:
    """Create, verify (PING) and store the shared Redis client."""
    global redis_client
    client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    await client.ping()
    redis_client = client
    return client


async def close_redis() -> None:
    """Close the shared Redis client if it is open."""
    global redis_client
    if redis_client is not None:
        await redis_client.close()
        redis_client = None


def get_redis_client() -> Optional[redis.Redis]:
    """Return the live Redis client, or None if not connected yet."""
    return redis_client
