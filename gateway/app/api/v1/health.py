"""
Health check and metrics endpoints.
"""
import time

from fastapi import APIRouter, status, Response
from sqlalchemy import text

from common.app.config import settings
from common.app.logging_config import setup_logger
from gateway.app.db.session import db_manager
from gateway.app.schemas.order import HealthCheckResponse
from gateway.app.services.kafka_producer import kafka_producer
from gateway.app.services.redis_client import get_redis_client

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = setup_logger(__name__)
router = APIRouter(tags=["Health"])
start_time = time.time()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """
    Comprehensive health check for all system components.
    Used by load balancers and orchestrators.
    """
    db_status = "unhealthy"
    kafka_status = "unhealthy"
    redis_status = "unhealthy"

    try:
        async with db_manager.get_session() as session:
            await session.execute(text("SELECT 1"))
            db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)[:50]}"

    try:
        kafka_status = "healthy" if kafka_producer.is_started else "not_started"
    except Exception as e:
        kafka_status = f"unhealthy: {str(e)[:50]}"

    try:
        redis_client = get_redis_client()
        if redis_client:
            await redis_client.ping()
            redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)[:50]}"

    overall_status = "healthy" if all(
        s == "healthy" for s in [db_status, kafka_status, redis_status]
    ) else "degraded"

    return HealthCheckResponse(
        status=overall_status,
        version=settings.VERSION,
        database=db_status,
        kafka=kafka_status,
        redis=redis_status,
        uptime_seconds=round(time.time() - start_time, 2),
    )


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe - checks if the service can accept traffic."""
    try:
        async with db_manager.get_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return Response(
            content='{"status": "not_ready"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json"
        )


@router.get("/metrics")
async def metrics():
    """Prometheus scrape endpoint (text exposition format)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
