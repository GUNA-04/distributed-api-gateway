"""
Event schemas for Kafka messages.
Provides a single source of truth for serialization across services.
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class OrderEventType(str, Enum):
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_PROCESSED = "PAYMENT_PROCESSED"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    SHIPPING_DISPATCHED = "SHIPPING_DISPATCHED"


class OrderEvent(BaseModel):
    event_id: str = Field(..., description="Unique event ID for idempotency")
    order_id: str
    user_id: str
    event_type: OrderEventType
    payload: dict
    retry_count: int = 0
    correlation_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrderRequest(BaseModel):
    user_id: str
    items: list[dict] = Field(..., min_length=1)
    total_amount: Decimal = Field(..., gt=0)
    shipping_address: str
    idempotency_key: Optional[str] = None


class OrderResponse(BaseModel):
    order_id: str
    status: OrderStatus
    message: str
    created_at: datetime
