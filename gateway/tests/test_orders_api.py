"""
Integration tests for order API endpoints.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from gateway.app.main import app


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_liveness_probe(client):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_ready_probe(client):
    response = await client.get("/health/ready")
    assert response.status_code in (200, 503)


@pytest.mark.asyncio
async def test_order_creation_requires_auth(client):
    response = await client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": "p1", "name": "Test", "quantity": 1, "unit_price": 10}],
            "total_amount": 10,
            "shipping_address": "123 Test Street, City, State 12345",
        }
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_rejected(client):
    response = await client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": "p1", "name": "Test", "quantity": 1, "unit_price": 10}],
            "total_amount": 10,
            "shipping_address": "123 Test Street, City, State 12345",
        },
        headers={"Authorization": "Bearer invalid-token-12345"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_registration_validation(client):
    """Test that invalid registration data returns 422 validation error."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "ab",
            "email": "not-an-email",
            "password": "short",
        }
    )
    assert response.status_code == 422
