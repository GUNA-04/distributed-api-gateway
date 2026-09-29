"""
Order processor service.
Implements business logic with retry, dead-letter, and idempotency handling.
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional
from aiokafka import AIOKafkaProducer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from common.app.config import settings
from common.app.logging_config import setup_logger
from common.app.schemas import OrderStatus, OrderEventType
from gateway.app.models.database import Order, ProcessedEvent

logger = setup_logger(__name__)


class ProcessingError(Exception):
    """Custom exception for order processing failures."""
    pass


class OrderProcessor:
    """
    Processes order events from Kafka with:
    - Idempotency via event_id tracking
    - Exponential backoff retry with jitter
    - Dead-letter queue for exhausted retries
    - Database transaction management
    """

    def __init__(self, session: AsyncSession, dlq_producer: Optional[AIOKafkaProducer] = None):
        self.session = session
        self.dlq_producer = dlq_producer

    async def _is_event_processed(self, event_id: str) -> bool:
        """Check if event was already processed."""
        stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _mark_event_processed(self, event_id: str, order_id: str):
        """Mark event as processed for idempotency."""
        processed = ProcessedEvent(
            event_id=event_id,
            order_id=uuid.UUID(str(order_id)),
            processed_at=datetime.utcnow(),
            ttl_at=datetime.utcnow() + timedelta(hours=24),
        )
        self.session.add(processed)
        await self.session.commit()

    async def process_order(self, event: dict) -> bool:
        """
        Core order processing with retry logic.
        Simulates payment, inventory, and shipping steps.
        """
        event_id = event.get("event_id")
        order_id = event.get("order_id")

        if await self._is_event_processed(event_id):
            logger.info(f"Event {event_id} already processed, skipping")
            return True

        logger.info(f"Processing order {order_id}")

        order_result = await self.session.execute(
            select(Order).where(Order.id == uuid.UUID(str(order_id)))
        )
        order = order_result.scalar_one_or_none()

        if not order:
            logger.error(f"Order {order_id} not found in database")
            return False

        if order.status == OrderStatus.COMPLETED.value:
            logger.info(f"Order {order_id} already completed")
            return True

        order.status = OrderStatus.PROCESSING.value
        order.updated_at = datetime.utcnow()
        await self.session.commit()

        try:
            await self._simulate_payment_processing(order)
            await self._simulate_inventory_check(order)
            await self._simulate_shipping_dispatch(order)
        except Exception as e:
            logger.error(f"Step failed for order {order_id}: {e}")
            raise

        order.status = OrderStatus.COMPLETED.value
        order.processed_at = datetime.utcnow()
        order.updated_at = datetime.utcnow()
        await self.session.commit()

        await self._mark_event_processed(event_id, str(order.id))

        logger.info(
            f"Order {order_id} processed successfully",
            extra={"event_id": event_id, "order_id": order_id}
        )
        return True

    async def _simulate_payment_processing(self, order: Order):
        """Simulate payment gateway call."""
        await asyncio.sleep(random.uniform(0.01, 0.05))
        logger.info(f"Payment processed for order {order.id}")

    async def _simulate_inventory_check(self, order: Order):
        """Simulate inventory reservation."""
        await asyncio.sleep(random.uniform(0.01, 0.05))
        logger.info(f"Inventory reserved for order {order.id}")

    async def _simulate_shipping_dispatch(self, order: Order):
        """Simulate shipping label generation."""
        await asyncio.sleep(random.uniform(0.01, 0.05))
        logger.info(f"Shipping dispatched for order {order.id}")

    async def handle_failure(self, event: dict, error: Exception):
        """Handle processing failure with retry/DLQ logic."""
        event_id = event.get("event_id")
        order_id = event.get("order_id")
        retry_count = event.get("retry_count", 0)

        logger.error(
            f"Order processing failed: {error}",
            extra={"order_id": order_id, "retry_count": retry_count}
        )

        order_result = await self.session.execute(
            select(Order).where(Order.id == uuid.UUID(str(order_id)))
        )
        order = order_result.scalar_one_or_none()

        new_retry_count = retry_count + 1

        if order:
            order.retry_count = new_retry_count
            order.error_message = str(error)[:500]
            order.updated_at = datetime.utcnow()

            if new_retry_count >= settings.MAX_RETRIES:
                order.status = OrderStatus.DEAD_LETTERED.value

            await self.session.commit()

        if new_retry_count >= settings.MAX_RETRIES:
            if self.dlq_producer:
                dlq_message = {
                    **event,
                    "error": str(error),
                    "retry_count": new_retry_count,
                    "dead_lettered_at": datetime.utcnow().isoformat(),
                }
                try:
                    await self.dlq_producer.send_and_wait(
                        settings.KAFKA_TOPIC_DLQ,
                        value=dlq_message,
                        key=order_id,
                    )
                    logger.warning(f"Order {order_id} moved to DLQ after {new_retry_count} retries")
                except Exception as e:
                    logger.error(f"Failed to send to DLQ: {e}")
        else:
            if self.dlq_producer:
                retry_message = {**event, "retry_count": new_retry_count}
                try:
                    await self.dlq_producer.send_and_wait(
                        settings.KAFKA_TOPIC_RETRIES,
                        value=retry_message,
                        key=order_id,
                    )
                    logger.info(f"Order {order_id} scheduled for retry {new_retry_count}")
                except Exception as e:
                    logger.error(f"Failed to send retry: {e}")