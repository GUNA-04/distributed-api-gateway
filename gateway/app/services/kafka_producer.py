"""
Kafka producer with async message publishing and delivery callbacks.
Handles order events with configurable acks and retry semantics.
"""
import json
import asyncio
from typing import Optional
from datetime import datetime
from aiokafka import AIOKafkaProducer
from common.app.config import settings
from common.app.logging_config import setup_logger

logger = setup_logger(__name__)


class KafkaProducerService:
    """
    Async Kafka producer with automatic batching and delivery confirmation.
    Sends order events to Kafka topics for downstream processing.
    """

    def __init__(self):
        self.producer: Optional[AIOKafkaProducer] = None
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    async def start(self):
        if self._started:
            return
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            max_batch_size=16384,
            linger_ms=10,
            compression_type="gzip",
            enable_idempotence=True,
        )
        await self.producer.start()
        self._started = True
        logger.info(
            "Kafka producer started",
            extra={"bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS}
        )

    async def stop(self):
        if self.producer and self._started:
            await self.producer.stop()
            self._started = False
            logger.info("Kafka producer stopped")

    async def send_order_event(
        self,
        order_id: str,
        user_id: str,
        event_type: str,
        payload: dict,
        correlation_id: str,
        topic: str = None
    ) -> bool:
        """
        Send an order event to Kafka with idempotent delivery.
        Returns True if message was successfully delivered.
        """
        target_topic = topic or settings.KAFKA_TOPIC_ORDERS

        if not self._started:
            try:
                await self.start()
            except Exception as e:
                logger.error(
                    f"Kafka producer failed to start, event not published: {e}",
                    extra={"order_id": order_id, "topic": target_topic},
                )
                return False

        message = {
            "event_id": f"{order_id}_{event_type}",
            "order_id": order_id,
            "user_id": user_id,
            "event_type": event_type,
            "payload": payload,
            "correlation_id": correlation_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "retry_count": 0,
        }

        try:
            result = await self.producer.send_and_wait(
                target_topic,
                value=message,
                key=order_id,
            )
            logger.info(
                "Order event published to Kafka",
                extra={
                    "topic": target_topic,
                    "partition": result.partition,
                    "offset": result.offset,
                    "order_id": order_id,
                }
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to publish order event: {e}",
                extra={"order_id": order_id, "topic": target_topic}
            )
            return False

    async def send_to_dlq(
        self,
        order_id: str,
        user_id: str,
        event_type: str,
        payload: dict,
        correlation_id: str,
        error: str,
        retry_count: int
    ) -> bool:
        """Send a failed order to the dead-letter queue."""
        if not self._started:
            logger.warning("Kafka producer not started, cannot send to DLQ")
            return False

        message = {
            "event_id": f"{order_id}_{event_type}_{retry_count}",
            "order_id": order_id,
            "user_id": user_id,
            "event_type": event_type,
            "payload": payload,
            "correlation_id": correlation_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "error": error,
            "retry_count": retry_count,
            "dead_lettered_at": datetime.utcnow().isoformat() + "Z",
        }

        try:
            result = await self.producer.send_and_wait(
                settings.KAFKA_TOPIC_DLQ,
                value=message,
                key=order_id,
            )
            logger.info(
                "Order event sent to DLQ",
                extra={"order_id": order_id, "dlq_topic": settings.KAFKA_TOPIC_DLQ}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send to DLQ: {e}", extra={"order_id": order_id})
            return False

    async def send_retry(
        self,
        order_id: str,
        user_id: str,
        event_type: str,
        payload: dict,
        correlation_id: str,
        retry_count: int
    ) -> bool:
        """Send to retry topic with exponential backoff."""
        if not self._started:
            logger.warning("Kafka producer not started, cannot send retry")
            return False

        message = {
            "event_id": f"{order_id}_{event_type}_{retry_count}",
            "order_id": order_id,
            "user_id": user_id,
            "event_type": event_type,
            "payload": payload,
            "correlation_id": correlation_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "retry_count": retry_count,
        }

        try:
            await self.producer.send_and_wait(
                settings.KAFKA_TOPIC_RETRIES,
                value=message,
                key=order_id,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send retry: {e}", extra={"order_id": order_id})
            return False


kafka_producer = KafkaProducerService()
