"""
Redis-backed rate limiter using sliding window algorithm.
Supports per-user, per-IP, and per-API-key rate limits.
"""
import time
import uuid
from typing import Optional, Tuple
from fastapi import Request, HTTPException, status
import redis.asyncio as redis
from common.app.config import settings
from common.app.logging_config import setup_logger

logger = setup_logger(__name__)


class RateLimiter:
    """
    Token bucket + sliding window rate limiter backed by Redis.
    Uses Redis sorted sets for precise sliding window tracking.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.window = settings.RATE_LIMIT_WINDOW_SECONDS
        self.max_requests = settings.RATE_LIMIT_REQUESTS

    async def _get_key(self, identifier: str, endpoint: str) -> str:
        return f"ratelimit:{endpoint}:{identifier}"

    async def is_allowed(
        self,
        identifier: str,
        endpoint: str,
        max_requests: Optional[int] = None,
        window: Optional[int] = None
    ) -> Tuple[bool, int, int]:
        """
        Check if request is allowed. Returns (allowed, remaining, reset_time).
        Uses sliding window log algorithm for accuracy.
        """
        key = await self._get_key(identifier, endpoint)
        now = time.time()
        window_sec = window or self.window
        limit = max_requests or self.max_requests
        window_start = now - window_sec

        # Remove expired entries
        await self.redis.zremrangebyscore(key, 0, window_start)
        # Count current entries in window
        current_count = await self.redis.zcard(key)
        reset_time = int(now + window_sec)

        if current_count >= limit:
            logger.warning(
                "Rate limit exceeded",
                extra={"identifier": identifier, "endpoint": endpoint, "count": current_count}
            )
            return False, 0, reset_time

        # Add current request
        await self.redis.zadd(key, {str(uuid.uuid4()): now})
        await self.redis.expire(key, window_sec + 1)

        remaining = max(0, limit - current_count - 1)
        return True, remaining, reset_time

    async def get_limit_tier(self, tier: str) -> Tuple[int, int]:
        """Get rate limits based on user tier."""
        tiers = {
            "free": (100, 60),
            "basic": (1000, 60),
            "premium": (5000, 60),
            "enterprise": (50000, 60),
        }
        return tiers.get(tier, tiers["free"])


_rate_limiter: RateLimiter = None


async def init_rate_limiter(redis_client: redis.Redis):
    global _rate_limiter
    _rate_limiter = RateLimiter(redis_client)


def get_rate_limiter() -> RateLimiter:
    if not _rate_limiter:
        raise RuntimeError("Rate limiter not initialized")
    return _rate_limiter


async def check_rate_limit(
    request: Request,
    user_id: str = None,
    tier: str = "free",
    custom_limit: int = None
) -> bool:
    """
    FastAPI dependency to enforce rate limiting.
    Raises HTTP 429 if limit exceeded, otherwise returns True.
    """
    limiter = get_rate_limiter()

    client_ip = request.client.host if request.client else "unknown"
    identifier = user_id or client_ip
    endpoint = request.url.path

    limit, window = await limiter.get_limit_tier(tier)
    if custom_limit:
        limit = custom_limit

    allowed, remaining, reset = await limiter.is_allowed(
        identifier, endpoint, limit, window
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Rate limit of {limit} requests per {window}s exceeded",
                "retry_after": reset - int(time.time())
            },
            headers={"Retry-After": str(reset - int(time.time()))}
        )

    request.state.rate_limit = {
        "remaining": remaining,
        "limit": limit,
        "reset": reset
    }
    return True
