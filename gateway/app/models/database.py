"""
Database models for the order processing system.
"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    Column, String, DateTime, Integer, Numeric,
    Index, ForeignKey, Text, Enum as SAEnum, Boolean
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base
import uuid
import enum

Base = declarative_base()


class OrderStatusModel(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    total_amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(50), nullable=False, default=OrderStatusModel.PENDING.value, index=True)
    items = Column(JSONB, nullable=False)
    shipping_address = Column(Text, nullable=False)
    idempotency_key = Column(String(255), unique=True, nullable=True, index=True)
    correlation_id = Column(String(255), nullable=False, index=True)
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_orders_created_status", "created_at", "status"),
        Index("ix_orders_user_created", "user_id", "created_at"),
    )


class ProcessedEvent(Base):
    """Table for idempotency tracking - stores processed event IDs."""
    __tablename__ = "processed_events"

    event_id = Column(String(255), primary_key=True)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ttl_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_processed_events_ttl", "ttl_at"),
    )


class User(Base):
    """User accounts for authentication."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    tier = Column(String(50), default="free", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_users_tier_active", "tier", "is_active"),
    )


class APIKey(Base):
    """API keys for programmatic access."""
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(255), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    rate_limit_override = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_api_keys_user_active", "user_id", "is_active"),
    )
