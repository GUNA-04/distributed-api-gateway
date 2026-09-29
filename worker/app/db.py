"""
Worker database session.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from common.app.config import settings
from common.app.logging_config import setup_logger

logger = setup_logger(__name__)


class WorkerDatabase:
    def __init__(self):
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        if self.engine is not None:
            return

        self.engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("Worker database pool initialized")

    async def close(self):
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None

    def get_session(self):
        if self.session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self.session_factory()


worker_db = WorkerDatabase()