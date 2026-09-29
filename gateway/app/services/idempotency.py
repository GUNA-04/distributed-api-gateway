"""
Idempotency service using Postgres unique constraints.
Prevents duplicate order processing on retry.
"""
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from common.app.logging_config import setup_logger
from common.app.config import settings

logger = setup_logger(__name__)


class IdempotencyService:
    """
    Implements idempotency using:
    1. Client-provided Idempotency-Key header (preferred)
    2. SHA-256 hash of request payload (fallback)
    3. Postgres unique constraint for race-condition safety
    """

    @staticmethod
    def generate_idempotency_key(payload: dict) -> str:
        """Generate deterministic hash of request payload."""
        serialized = sorted(payload.items())
        return hashlib.sha256(str(serialized).encode()).hexdigest()

    @staticmethod
    async def check_processed(
        db: AsyncSession,
        event_id: str,
        order_id: str = "00000000-0000-0000-0000-000000000000",
        ttl_hours: int = 24
    ) -> bool:
        """
        Atomically mark an event as processed and return whether it was a duplicate.
        Returns True if event was already processed (duplicate), False if newly inserted.
        Uses ON CONFLICT DO NOTHING for race-condition safety.
        """
        ttl_at = datetime.utcnow() + timedelta(hours=ttl_hours)

        stmt = text("""
            INSERT INTO processed_events (event_id, order_id, processed_at, ttl_at)
            VALUES (:event_id, :order_id, :processed_at, :ttl_at)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
        """)

        try:
            result = await db.execute(stmt, {
                "event_id": event_id,
                "order_id": order_id,
                "processed_at": datetime.utcnow(),
                "ttl_at": ttl_at
            })
            await db.commit()
            # ON CONFLICT DO NOTHING + RETURNING: a row means this is a fresh
            # insert (not a duplicate); no row means the event_id already existed.
            return result.fetchone() is None
        except IntegrityError:
            await db.rollback()
            return True

    @staticmethod
    async def cleanup_expired(db: AsyncSession):
        """Clean up expired idempotency records (called periodically)."""
        from gateway.app.models.database import ProcessedEvent

        stmt = delete(ProcessedEvent).where(ProcessedEvent.ttl_at < datetime.utcnow())
        result = await db.execute(stmt)
        await db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} expired idempotency records")
        return deleted
