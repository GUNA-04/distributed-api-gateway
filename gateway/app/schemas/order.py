"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class OrderItemSchema(BaseModel):
    product_id: str
    name: str
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., gt=0)

    model_config = ConfigDict(from_attributes=True)


class OrderCreateRequest(BaseModel):
    items: List[OrderItemSchema] = Field(..., min_length=1)
    total_amount: Decimal = Field(..., gt=0)
    shipping_address: str = Field(..., min_length=10, max_length=500)
    idempotency_key: Optional[str] = Field(None, max_length=255)


class OrderCreateResponse(BaseModel):
    order_id: str
    status: str
    message: str
    created_at: datetime
    idempotency_key: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrderStatusResponse(BaseModel):
    order_id: str
    user_id: str
    status: str
    total_amount: Decimal
    items: List[dict]
    shipping_address: str
    created_at: datetime
    processed_at: Optional[datetime] = None
    retry_count: int = 0
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=100)


class HealthCheckResponse(BaseModel):
    status: str
    version: str
    database: str
    kafka: str
    redis: str
    uptime_seconds: float
