"""
Unit tests for the idempotency service.

The service claims event IDs with INSERT ... ON CONFLICT DO NOTHING
RETURNING event_id:
  - fresh insert  -> a row is returned  -> NOT a duplicate (False)
  - conflict      -> no row is returned -> duplicate (True)
These tests pin that contract, which the order API depends on.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import IntegrityError

from gateway.app.services.idempotency import IdempotencyService


def _session_returning(rows):
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = rows[0] if rows else None
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_new_event_is_not_a_duplicate():
    session = _session_returning(rows=[("event-1",)])
    is_dup = await IdempotencyService.check_processed(session, "event-1", "order-1")
    assert is_dup is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_event_is_a_duplicate():
    session = _session_returning(rows=[])  # ON CONFLICT DO NOTHING -> no row
    is_dup = await IdempotencyService.check_processed(session, "event-1", "order-1")
    assert is_dup is True


@pytest.mark.asyncio
async def test_integrity_error_treated_as_duplicate():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=IntegrityError("dup", {}, Exception("uniq")))
    is_dup = await IdempotencyService.check_processed(session, "event-1", "order-1")
    assert is_dup is True
    session.rollback.assert_awaited_once()


def test_generated_idempotency_key_is_deterministic():
    payload = {"items": [{"product_id": "p1"}], "total": "10.00"}
    key_a = IdempotencyService.generate_idempotency_key(payload)
    key_b = IdempotencyService.generate_idempotency_key(payload)
    assert key_a == key_b
    assert len(key_a) == 64  # sha256 hex digest
