"""
Unit tests for the Kafka producer service.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from gateway.app.services.kafka_producer import kafka_producer


@pytest.fixture
def started_producer(monkeypatch):
    """Give the singleton producer a started, mocked AIOKafkaProducer."""
    inner = AsyncMock()
    metadata = MagicMock()
    metadata.partition = 0
    metadata.offset = 42
    inner.send_and_wait = AsyncMock(return_value=metadata)
    monkeypatch.setattr(kafka_producer, "producer", inner)
    monkeypatch.setattr(kafka_producer, "_started", True)
    return inner


@pytest.mark.asyncio
async def test_send_order_event_success(started_producer):
    ok = await kafka_producer.send_order_event(
        order_id="order-1",
        user_id="user-1",
        event_type="ORDER_CREATED",
        payload={"total_amount": "10.00"},
        correlation_id="corr-1",
    )
    assert ok is True

    args, kwargs = started_producer.send_and_wait.call_args
    assert args[0] == "orders"          # default topic
    assert kwargs["key"] == "order-1"   # partition key for ordering

    message = kwargs["value"]
    assert message["event_id"] == "order-1_ORDER_CREATED"
    assert message["retry_count"] == 0
    assert message["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_send_order_event_broker_error_returns_false(started_producer, monkeypatch):
    started_producer.send_and_wait = AsyncMock(side_effect=Exception("broker down"))
    ok = await kafka_producer.send_order_event(
        order_id="order-1",
        user_id="user-1",
        event_type="ORDER_CREATED",
        payload={},
        correlation_id="corr-1",
    )
    assert ok is False  # caller stores the order and logs, never crashes


@pytest.mark.asyncio
async def test_send_order_event_producer_start_failure(monkeypatch):
    """If Kafka cannot be reached at start() time, publishing fails gracefully."""
    monkeypatch.setattr(kafka_producer, "_started", False)

    async def boom():
        raise Exception("Kafka unreachable")

    monkeypatch.setattr(kafka_producer, "start", boom)
    ok = await kafka_producer.send_order_event(
        order_id="order-1",
        user_id="user-1",
        event_type="ORDER_CREATED",
        payload={},
        correlation_id="corr-1",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_send_to_dlq_when_not_started_returns_false(monkeypatch):
    monkeypatch.setattr(kafka_producer, "_started", False)
    ok = await kafka_producer.send_to_dlq(
        order_id="order-1", user_id="user-1", event_type="ORDER_CREATED",
        payload={}, correlation_id="corr-1", error="boom", retry_count=3,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_send_retry_targets_retry_topic(started_producer):
    ok = await kafka_producer.send_retry(
        order_id="order-1", user_id="user-1", event_type="ORDER_CREATED",
        payload={}, correlation_id="corr-1", retry_count=1,
    )
    assert ok is True
    args, kwargs = started_producer.send_and_wait.call_args
    assert args[0] == "orders.retry"
    assert kwargs["value"]["retry_count"] == 1


@pytest.mark.asyncio
async def test_send_to_dlq_targets_dlq_topic(started_producer):
    ok = await kafka_producer.send_to_dlq(
        order_id="order-1", user_id="user-1", event_type="ORDER_CREATED",
        payload={}, correlation_id="corr-1", error="boom", retry_count=3,
    )
    assert ok is True
    args, kwargs = started_producer.send_and_wait.call_args
    assert args[0] == "orders.dlq"
    assert kwargs["value"]["error"] == "boom"
