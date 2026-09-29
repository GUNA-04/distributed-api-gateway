"""
FastAPI Application Factory.
Main entry point for the API Gateway service.
"""
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from common.app.config import settings
from common.app.logging_config import setup_logger
from gateway.app.db.session import db_manager
from gateway.app.services.rate_limiter import init_rate_limiter
from gateway.app.services.redis_client import connect_redis, close_redis
from gateway.app.services.kafka_producer import kafka_producer
from gateway.app.services.metrics import (
    IN_FLIGHT,
    RATE_LIMITED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    route_path,
)
from gateway.app.api.v1 import orders, auth, health

logger = setup_logger(__name__)
start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Starting API Gateway...")

    try:
        await db_manager.initialize()
        logger.info("Database pool initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    try:
        redis_client = await connect_redis()
        await init_rate_limiter(redis_client)
        logger.info("Redis rate limiter initialized")
    except Exception as e:
        logger.error(f"Redis initialization failed: {e}")
        raise

    try:
        await kafka_producer.start()
    except Exception as e:
        logger.warning(f"Kafka not available: {e}. Running in degraded mode.")

    logger.info(
        "API Gateway ready",
        extra={"version": settings.VERSION, "uptime": round(time.time() - start_time, 2)}
    )

    yield

    logger.info("Shutting down API Gateway...")
    try:
        await kafka_producer.stop()
    except Exception as e:
        logger.error(f"Error stopping Kafka producer: {e}")

    try:
        await close_redis()
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")

    try:
        await db_manager.close()
    except Exception as e:
        logger.error(f"Error closing database: {e}")

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Distributed Rate-Limited API Gateway with Event-Driven Order Processing",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"],
    )

    @app.middleware("http")
    async def add_request_metadata(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", f"req-{time.time_ns()}")
        request.state.request_id = request_id
        request.state.start_time = time.time()
        IN_FLIGHT.inc()

        response = await call_next(request)

        elapsed = (time.time() - request.state.start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(round(elapsed, 2))

        path = route_path(request)
        REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed / 1000)
        IN_FLIGHT.dec()
        if response.status_code == 429:
            RATE_LIMITED.inc()

        logger.info(
            f"{request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": round(elapsed, 2),
                "client_ip": request.client.host if request.client else "unknown",
            }
        )

        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_server_error", "message": "An unexpected error occurred"}
        )

    app.include_router(health.router)
    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(orders.router, prefix=settings.API_V1_STR)

    return app


app = create_app()