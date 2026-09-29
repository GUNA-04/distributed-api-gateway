"""
Integration-style tests for the register -> login -> create-order flow.

Uses FastAPI dependency overrides to swap the real Postgres session for an
in-memory fake, and a mocked Redis (rate limiter) + Kafka producer, so the
full HTTP stack (routing, auth, validation, idempotency, metrics) is tested
without any external services.
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from gateway.app.main import app
from gateway.app.db.session import get_db
from gateway.app.core.security import hash_password
from gateway.app.services.rate_limiter import init_rate_limiter
from gateway.app.services.kafka_producer import kafka_producer


class FakeResult:
    """Mimics the pieces of a SQLAlchemy Result the API actually uses."""

    def __init__(self, scalar: Any = None, rows: Optional[list] = None):
        self._scalar = scalar
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """
    In-memory stand-in for AsyncSession.

    Routes queries by inspecting the statement SQL, which is enough for the
    endpoints under test. State is shared at class level so successive HTTP
    requests behave like one database.
    """

    store: dict = {}

    @classmethod
    def reset(cls):
        cls.store = {"users": [], "orders": [], "events": set()}

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO processed_events" in sql:
            event_id = params["event_id"]
            if event_id in self.store["events"]:
                return FakeResult(rows=[])  # conflict -> duplicate
            self.store["events"].add(event_id)
            return FakeResult(rows=[(event_id,)])  # fresh insert
        if "FROM users" in sql:
            users = self.store["users"]
            return FakeResult(scalar=users[0] if users else None, rows=users)
        if "FROM orders" in sql:
            orders = self.store["orders"]
            return FakeResult(scalar=orders[0] if orders else None, rows=orders)
        return FakeResult()

    def add(self, obj):
        name = type(obj).__name__
        if name == "User":
            self.store["users"].append(obj)
        elif name == "Order":
            self.store["orders"].append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()


@pytest.fixture
def fake_session():
    FakeSession.reset()
    return FakeSession()


@pytest.fixture
def mock_redis_limiter():
    redis = AsyncMock()
    redis.zremrangebyscore = AsyncMock()
    redis.zcard = AsyncMock(return_value=0)
    redis.zadd = AsyncMock()
    redis.expire = AsyncMock()
    redis.ttl = AsyncMock(return_value=60)
    return redis


@pytest.fixture
async def flow_client(fake_session, mock_redis_limiter, monkeypatch):
    app.dependency_overrides[get_db] = lambda: fake_session
    await init_rate_limiter(mock_redis_limiter)

    # Kafka is not available in unit tests; publish calls succeed via mock.
    monkeypatch.setattr(kafka_producer, "send_order_event", AsyncMock(return_value=True))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


async def _register_and_login(client, username="flowuser", password="password123"):
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    return reg, login


@pytest.mark.asyncio
async def test_register_creates_user(flow_client):
    reg, _ = await _register_and_login(flow_client)
    assert reg.status_code == 201
    body = reg.json()
    assert body["username"] == "flowuser"
    assert body["user_id"]


@pytest.mark.asyncio
async def test_register_duplicate_username_conflict(flow_client):
    await _register_and_login(flow_client)
    reg2 = await flow_client.post(
        "/api/v1/auth/register",
        json={
            "username": "flowuser",
            "email": "other@example.com",
            "password": "password123",
        },
    )
    assert reg2.status_code == 409


@pytest.mark.asyncio
async def test_register_invalid_email_rejected(flow_client):
    response = await flow_client.post(
        "/api/v1/auth/register",
        json={
            "username": "newuser",
            "email": "not-an-email",
            "password": "password123",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_returns_token(flow_client):
    _, login = await _register_and_login(flow_client)
    assert login.status_code == 200
    body = login.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_unauthorized(flow_client):
    await _register_and_login(flow_client, username="flowuser2")
    response = await flow_client.post(
        "/api/v1/auth/login",
        data={"username": "flowuser2", "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_order_requires_token(flow_client):
    response = await flow_client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": "9.99"}],
            "total_amount": "9.99",
            "shipping_address": "123 Test Street, Springfield, 12345",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_order_happy_path(flow_client):
    _, login = await _register_and_login(flow_client)
    token = login.json()["access_token"]

    response = await flow_client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": "p1", "name": "Widget", "quantity": 2, "unit_price": "9.99"}],
            "total_amount": "19.98",
            "shipping_address": "123 Test Street, Springfield, 12345",
        },
        headers={"Authorization": f"Bearer {token}", "X-Idempotency-Key": "key-abc-1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["idempotency_key"] == "key-abc-1"
    kafka_producer.send_order_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotent_replay_returns_same_order(flow_client):
    _, login = await _register_and_login(flow_client)
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "key-abc-2"}
    order_payload = {
        "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": "5.00"}],
        "total_amount": "5.00",
        "shipping_address": "123 Test Street, Springfield, 12345",
    }

    first = await flow_client.post("/api/v1/orders", json=order_payload, headers=headers)
    second = await flow_client.post("/api/v1/orders", json=order_payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["order_id"] == second.json()["order_id"]
    assert "idempotent" in second.json()["message"].lower()
    # Only the first request should have reached Kafka.
    assert kafka_producer.send_order_event.await_count == 1


@pytest.mark.asyncio
async def test_get_order_by_id(flow_client):
    _, login = await _register_and_login(flow_client)
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = await flow_client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": "5.00"}],
            "total_amount": "5.00",
            "shipping_address": "123 Test Street, Springfield, 12345",
        },
        headers=headers,
    )
    order_id = created.json()["order_id"]

    fetched = await flow_client.get(f"/api/v1/orders/{order_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["order_id"] == order_id
    assert fetched.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_list_orders(flow_client):
    _, login = await _register_and_login(flow_client)
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await flow_client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": "5.00"}],
            "total_amount": "5.00",
            "shipping_address": "123 Test Street, Springfield, 12345",
        },
        headers=headers,
    )

    response = await flow_client.get("/api/v1/orders", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_health_degraded_without_infra():
    """Without lifespan startup (no DB/Redis), /health must report degraded, not crash."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
