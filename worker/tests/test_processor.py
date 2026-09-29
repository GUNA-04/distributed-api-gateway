"""
Tests for order processor service.
"""
import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock

from worker.app.processor import OrderProcessor, ProcessingError


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()  # add() is sync on the real session
    return session


@pytest.fixture
def sample_event():
    return {
        "event_id": "order_123_ORDER_CREATED",
        "order_id": "550e8400-e29b-41d4-a716-446655440000",
        "user_id": "user_123",
        "event_type": "ORDER_CREATED",
        "payload": {
            "items": [{"product_id": "p1", "quantity": 2}],
            "total_amount": "100.00",
        },
        "correlation_id": "corr_123",
        "retry_count": 0,
    }


@pytest.mark.asyncio
async def test_is_event_processed_false(mock_session, sample_event):
    processor = OrderProcessor(mock_session, None)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await processor._is_event_processed(sample_event["event_id"])
    assert result is False


@pytest.mark.asyncio
async def test_is_event_processed_true(mock_session, sample_event):
    processor = OrderProcessor(mock_session, None)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await processor._is_event_processed(sample_event["event_id"])
    assert result is True


@pytest.mark.asyncio
async def test_order_processor_initialization(mock_session):
    processor = OrderProcessor(mock_session)
    assert processor.session == mock_session
    assert processor.dlq_producer is None

    mock_dlq = AsyncMock()
    processor_with_dlq = OrderProcessor(mock_session, mock_dlq)
    assert processor_with_dlq.dlq_producer == mock_dlq


def _result(value):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    return mock_result


@pytest.mark.asyncio
async def test_process_order_happy_path(mock_session, sample_event):
    """New event + existing PENDING order -> payment/inventory/shipping run,
    order becomes COMPLETED and the event is marked processed."""
    processor = OrderProcessor(mock_session, None)

    order = MagicMock()
    order.id = uuid.UUID(sample_event["order_id"])
    order.status = "PENDING"

    mock_session.execute = AsyncMock(side_effect=[_result(None), _result(order)])
    for step in (
        "_simulate_payment_processing",
        "_simulate_inventory_check",
        "_simulate_shipping_dispatch",
    ):
        setattr(processor, step, AsyncMock())

    assert await processor.process_order(sample_event) is True
    assert order.status == "COMPLETED"
    assert order.processed_at is not None
    mock_session.commit.assert_awaited()
    mock_session.add.assert_called_once()  # ProcessedEvent row


@pytest.mark.asyncio
async def test_process_order_duplicate_event_skipped(mock_session, sample_event):
    processor = OrderProcessor(mock_session, None)
    mock_session.execute = AsyncMock(side_effect=[_result(MagicMock())])  # event already processed

    assert await processor.process_order(sample_event) is True
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_order_missing_order_returns_false(mock_session, sample_event):
    processor = OrderProcessor(mock_session, None)
    mock_session.execute = AsyncMock(side_effect=[_result(None), _result(None)])

    assert await processor.process_order(sample_event) is False


@pytest.mark.asyncio
async def test_process_order_completed_order_short_circuits(mock_session, sample_event):
    processor = OrderProcessor(mock_session, None)
    order = MagicMock()
    order.status = "COMPLETED"
    mock_session.execute = AsyncMock(side_effect=[_result(None), _result(order)])

    assert await processor.process_order(sample_event) is True
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_failure_schedules_retry(mock_session, sample_event):
    """Below the retry ceiling the event goes to the retry topic, not the DLQ."""
    mock_producer = AsyncMock()
    processor = OrderProcessor(mock_session, mock_producer)

    order = MagicMock()
    mock_session.execute = AsyncMock(return_value=_result(order))

    await processor.handle_failure(sample_event, Exception("payment gateway timeout"))

    assert order.retry_count == 1
    assert order.status != "DEAD_LETTERED"
    args, kwargs = mock_producer.send_and_wait.call_args
    assert args[0] == "orders.retry"
    assert kwargs["value"]["retry_count"] == 1


@pytest.mark.asyncio
async def test_handle_failure_dead_letters_after_max_retries(mock_session, sample_event):
    mock_producer = AsyncMock()
    processor = OrderProcessor(mock_session, mock_producer)

    order = MagicMock()
    mock_session.execute = AsyncMock(return_value=_result(order))
    sample_event["retry_count"] = 3  # already at MAX_RETRIES (3)

    await processor.handle_failure(sample_event, Exception("still failing"))

    assert order.status == "DEAD_LETTERED"
    args, kwargs = mock_producer.send_and_wait.call_args
    assert args[0] == "orders.dlq"
    assert "still failing" in kwargs["value"]["error"]


@pytest.mark.asyncio
async def test_handle_failure_missing_order_still_routes_to_retry(mock_session, sample_event):
    mock_producer = AsyncMock()
    processor = OrderProcessor(mock_session, mock_producer)
    mock_session.execute = AsyncMock(return_value=_result(None))

    await processor.handle_failure(sample_event, Exception("boom"))

    args, _ = mock_producer.send_and_wait.call_args
    assert args[0] == "orders.retry"
