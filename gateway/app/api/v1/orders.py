"""
API v1 routes for orders.
"""
import uuid
import time
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from common.app.schemas import OrderStatus, OrderEventType
from common.app.logging_config import setup_logger
from gateway.app.db.session import get_db
from gateway.app.core.security import get_current_user
from gateway.app.models.database import Order, User
from gateway.app.schemas.order import (
    OrderCreateRequest,
    OrderCreateResponse,
    OrderStatusResponse,
)
from gateway.app.services.kafka_producer import kafka_producer
from gateway.app.services.idempotency import IdempotencyService
from gateway.app.services.rate_limiter import check_rate_limit
from gateway.app.services.metrics import ORDERS_CREATED, ORDERS_QUEUED_FAILED

logger = setup_logger(__name__)
router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("", response_model=OrderCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    request: Request,
    order_req: OrderCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Create a new order. Orders are published to Kafka for async processing.
    Supports idempotency via X-Idempotency-Key header.
    """
    await check_rate_limit(request, user_id=str(user.id), tier=user.tier)

    start_time = time.time()

    idempotency_key = x_idempotency_key or order_req.idempotency_key
    correlation_id = str(uuid.uuid4())

    if idempotency_key:
        # Fast path: the client is retrying with a known key - replay the
        # original response instead of creating a duplicate order.
        existing = await db.execute(
            select(Order).where(Order.idempotency_key == idempotency_key)
        )
        existing_order = existing.scalar_one_or_none()
        if existing_order:
            logger.info(
                "Returning cached response for idempotent request",
                extra={"idempotency_key": idempotency_key}
            )
            return OrderCreateResponse(
                order_id=str(existing_order.id),
                status=existing_order.status,
                message="Order already processed (idempotent response)",
                created_at=existing_order.created_at,
                idempotency_key=idempotency_key,
            )

    event_id = idempotency_key or f"{user.id}_{correlation_id}"

    # mode="json" converts Decimal/datetime values so they are safe for the
    # JSONB column and Kafka's JSON serializer.
    items_json = [item.model_dump(mode="json") for item in order_req.items]

    order = Order(
        id=uuid.uuid4(),
        user_id=str(user.id),
        total_amount=order_req.total_amount,
        status=OrderStatus.PENDING.value,
        items=items_json,
        shipping_address=order_req.shipping_address,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        retry_count=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    try:
        db.add(order)
        await db.commit()
        await db.refresh(order)
    except IntegrityError:
        # Lost a race against a concurrent request using the same idempotency key.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order with this idempotency key already exists.",
        )

    # Claim the event id only after the order is durably stored, so a failed
    # insert never burns the client's idempotency key.
    already_claimed = await IdempotencyService.check_processed(db, event_id, str(user.id))
    if already_claimed:
        logger.warning(
            "Event id already claimed (order row is authoritative)",
            extra={"event_id": event_id, "order_id": str(order.id)},
        )

    payload = {
        "items": items_json,
        "total_amount": str(order_req.total_amount),
        "shipping_address": order_req.shipping_address,
    }

    kafka_success = await kafka_producer.send_order_event(
        order_id=str(order.id),
        user_id=str(user.id),
        event_type=OrderEventType.ORDER_CREATED.value,
        payload=payload,
        correlation_id=correlation_id,
    )

    if not kafka_success:
        ORDERS_QUEUED_FAILED.inc()
        logger.warning(
            "Kafka publish failed, order stored but not queued",
            extra={"order_id": str(order.id)}
        )
    else:
        ORDERS_CREATED.inc()

    elapsed = (time.time() - start_time) * 1000
    logger.info(
        "Order created",
        extra={
            "order_id": str(order.id),
            "user_id": str(user.id),
            "elapsed_ms": round(elapsed, 2),
            "kafka_queued": kafka_success
        }
    )

    return OrderCreateResponse(
        order_id=str(order.id),
        status=OrderStatus.PENDING.value,
        message="Order created and queued for processing",
        created_at=order.created_at,
        idempotency_key=idempotency_key,
    )


@router.get("/{order_id}", response_model=OrderStatusResponse)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get order status by ID."""
    result = await db.execute(
        select(Order).where(
            and_(Order.id == order_id, Order.user_id == str(user.id))
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    return OrderStatusResponse(
        order_id=str(order.id),
        user_id=order.user_id,
        status=order.status,
        total_amount=order.total_amount,
        items=order.items,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        processed_at=order.processed_at,
        retry_count=order.retry_count,
        error_message=order.error_message,
    )


@router.get("", response_model=list[OrderStatusResponse])
async def list_orders(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List orders for the current user with optional filtering."""
    await check_rate_limit(request, user_id=str(user.id), tier=user.tier)

    query = select(Order).where(Order.user_id == str(user.id))

    if status_filter:
        query = query.where(Order.status == status_filter)

    query = query.order_by(Order.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    orders = result.scalars().all()

    return [
        OrderStatusResponse(
            order_id=str(o.id),
            user_id=o.user_id,
            status=o.status,
            total_amount=o.total_amount,
            items=o.items,
            shipping_address=o.shipping_address,
            created_at=o.created_at,
            processed_at=o.processed_at,
            retry_count=o.retry_count,
            error_message=o.error_message,
        )
        for o in orders
    ]
