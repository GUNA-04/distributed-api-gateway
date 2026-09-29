"""
Unit tests for the rate limiter service.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from gateway.app.services.rate_limiter import RateLimiter


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.zremrangebyscore = AsyncMock()
    redis.zcard = AsyncMock(return_value=5)
    redis.zadd = AsyncMock()
    redis.expire = AsyncMock()
    redis.ttl = AsyncMock(return_value=60)
    return redis


@pytest.mark.asyncio
async def test_rate_limit_allows_under_limit(mock_redis):
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard = AsyncMock(return_value=5)
    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()

    limiter = RateLimiter(mock_redis)
    allowed, remaining, reset = await limiter.is_allowed("user123", "/api/v1/orders", max_requests=100, window=60)

    assert allowed is True
    assert remaining >= 0
    assert reset > 0
    mock_redis.zremrangebyscore.assert_called_once()
    mock_redis.zcard.assert_called_once()
    mock_redis.zadd.assert_called_once()
    mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limit_rejects_over_limit(mock_redis):
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard = AsyncMock(return_value=100)
    mock_redis.ttl = AsyncMock(return_value=30)

    limiter = RateLimiter(mock_redis)
    allowed, remaining, reset = await limiter.is_allowed(
        "user123", "/api/v1/orders", max_requests=100, window=60
    )

    assert allowed is False
    assert remaining == 0
    assert reset > 0


@pytest.mark.asyncio
async def test_rate_limit_first_request(mock_redis):
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard = AsyncMock(return_value=0)
    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()

    limiter = RateLimiter(mock_redis)
    allowed, remaining, reset = await limiter.is_allowed("newuser", "/api/v1/orders", max_requests=100, window=60)

    assert allowed is True
    assert remaining == 99
