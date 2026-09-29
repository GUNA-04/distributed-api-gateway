"""
Async database session factory with connection pooling.
Optimized for high-throughput async API workloads.
"""
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.pool import QueuePool
from sqlalchemy import text
from common.app.config import settings
from common.app.logging_config import setup_logger

logger = setup_logger(__name__)


class DatabaseManager:
    """Manages connection pooling across the gateway lifecycle."""

    def __init__(self):
        self.engine = None
        self.session_factory = None
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
            echo=settings.DEBUG,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._initialized = True
        logger.info(
            "Database connection pool initialized",
            extra={"pool_size": settings.DB_POOL_SIZE, "max_overflow": settings.DB_MAX_OVERFLOW}
        )

    async def close(self):
        if self.engine:
            await self.engine.dispose()
            self._initialized = False
            logger.info("Database connection pool closed")

    def get_session(self) -> AsyncSession:
        if not self._initialized or not self.session_factory:
            raise RuntimeError("Database not initialized")
        return self.session_factory()


db_manager = DatabaseManager()


async def get_db() -> AsyncSession:
    """FastAPI dependency for database session injection."""
    if not db_manager._initialized:
        await db_manager.initialize()
    async with db_manager.get_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
