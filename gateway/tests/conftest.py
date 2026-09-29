"""
Shared test fixtures for gateway tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from gateway.app.main import app


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mock_db():
    """Mock database session for unit tests."""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis client for rate limiter tests."""
    redis = AsyncMock()
    return redis


@pytest.fixture
def sample_user():
    """Sample user data for tests."""
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "username": "testuser",
        "email": "test@example.com",
        "tier": "free",
        "is_active": True,
    }