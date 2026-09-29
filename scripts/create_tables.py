"""
Create all database tables from the SQLAlchemy models.

Local development helper. The production path is scripts/init_db.sql (run
automatically by docker-compose) or Alembic migrations.

Usage:
    python scripts/create_tables.py
"""
import asyncio
import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine

from common.app.config import settings
from common.app.logging_config import setup_logger
import gateway.app.models.database  # noqa: F401  (registers all models on Base)
from gateway.app.models.database import Base

logger = setup_logger(__name__)


async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(
            "Tables created",
            extra={"database": settings.POSTGRES_DB, "tables": list(Base.metadata.tables)},
        )
        print(f"Created tables: {', '.join(Base.metadata.tables)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
