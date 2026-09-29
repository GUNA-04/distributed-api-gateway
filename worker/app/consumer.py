"""
Kafka consumer worker.
Consumes from orders and orders.retry topics, processes with backpressure control.
"""
import asyncio
import json
import signal
import time
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord
from common.app.config import settings
from common.app.logging_config import setup_logger
from worker.app.db import worker_db
from worker.app.processor import OrderProcessor

logger = setup_logger(__name__)


class OrderWorker:
    """
    Kafka consumer worker with:
    - Graceful shutdown handling
    - Consumer group management
    - Backpressure control via max poll records
    - Shared DLQ/retry producer
    """

    def __init__(self):
        self.consumer: AIOKafkaConsumer = None
        self.dlq_producer: AIOKafkaProducer = None
        self.running = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        await worker_db.initialize()
        await self._init_consumer()
        await self._init_producers()
        self.running = True
        logger.info(
            "Order worker started",
            extra={
                "consumer_group": settings.KAFKA_CONSUMER_GROUP,
                "topics": [settings.KAFKA_TOPIC_ORDERS, settings.KAFKA_TOPIC_RETRIES],
                "concurrency": settings.WORKER_CONCURRENCY,
            }
        )

    async def _init_consumer(self):
        self.consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC_ORDERS,
            settings.KAFKA_TOPIC_RETRIES,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_records=settings.WORKER_BATCH_SIZE,
            max_poll_interval_ms=300000,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await self.consumer.start()

    async def _init_producers(self):
        """Initialize shared producer for DLQ and retry topics."""
        self.dlq_producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            acks="all",
            enable_idempotence=True,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self.dlq_producer.start()

    async def process_message(self, message: ConsumerRecord):
        """Process a single Kafka message."""
        start_time = time.time()
        event = message.value

        logger.info(
            f"Received message from {message.topic}",
            extra={
                "topic": message.topic,
                "partition": message.partition,
                "offset": message.offset,
                "order_id": event.get("order_id"),
            }
        )

        async with worker_db.get_session() as session:
            processor = OrderProcessor(session, self.dlq_producer)

            try:
                success = await processor.process_order(event)
                elapsed = (time.time() - start_time) * 1000

                if success:
                    logger.info(
                        f"Successfully processed order {event.get('order_id')}",
                        extra={"elapsed_ms": round(elapsed, 2)}
                    )
                else:
                    await processor.handle_failure(event, Exception("Processing returned False"))

            except Exception as e:
                try:
                    await processor.handle_failure(event, e)
                except Exception as inner_e:
                    logger.error(f"handle_failure also failed: {inner_e}")
                logger.error(f"Message processing failed: {e}")

    async def run(self):
        """Main consumption loop with graceful shutdown."""
        logger.info("Starting message consumption loop...")

        while self.running:
            try:
                records = await self.consumer.getmany(
                    timeout_ms=settings.WORKER_POLL_TIMEOUT_MS,
                    max_records=settings.WORKER_BATCH_SIZE,
                )

                tasks = []
                for tp, msgs in records.items():
                    for msg in msgs:
                        tasks.append(self.process_message(msg))

                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, Exception):
                            logger.error(f"Task failed in batch: {r}")
                    await self.consumer.commit()

            except asyncio.CancelledError:
                logger.info("Worker cancelled, shutting down gracefully...")
                break
            except Exception as e:
                logger.error(f"Error in consumption loop: {e}")
                await asyncio.sleep(5)

        await self._shutdown()

    async def _shutdown(self):
        """Graceful shutdown sequence."""
        self.running = False
        logger.info("Initiating graceful shutdown...")

        if self.consumer:
            try:
                await self.consumer.stop()
            except Exception as e:
                logger.error(f"Error stopping consumer: {e}")

        if self.dlq_producer:
            try:
                await self.dlq_producer.stop()
            except Exception as e:
                logger.error(f"Error stopping DLQ producer: {e}")

        await worker_db.close()
        logger.info("Worker shutdown complete")

    async def stop(self):
        """Signal the worker to stop."""
        self.running = False
        self._shutdown_event.set()


async def main():
    worker = OrderWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            pass

    await worker.start()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())