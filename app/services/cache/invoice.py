import json
import logging
from typing import Optional, Any, List
from datetime import datetime, date
from decimal import Decimal

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 300


def _serialize_obj(obj: Any) -> Any:
    """Convert Pydantic models, datetime, and Decimal to JSON-safe types."""
    if hasattr(obj, "model_dump"):
        try:
            # Pydantic v2 handles datetime/Decimal natively with mode="json"
            return obj.model_dump(mode="json")
        except TypeError:
            # Fallback for Pydantic v1
            return obj.dict()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    return obj


def _build_cache_key(
    tenant_id: int,
    status_filter: Optional[str],
    booking_id: Optional[int],
) -> str:
    return f"invoices:tenant_{tenant_id}:status_{status_filter or 'all'}:booking_{booking_id or 'all'}"


async def get_cached_invoice_list(
    tenant_id: int,
    status_filter: Optional[str] = None,
    booking_id: Optional[int] = None
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        key = _build_cache_key(tenant_id, status_filter, booking_id)
        cached = await redis.get(key)
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read invoice cache: {e}")
        return None


async def set_cached_invoice_list(
    tenant_id: int,
    status_filter: Optional[str] = None,
    booking_id: Optional[int] = None,
    invoices: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        key = _build_cache_key(tenant_id, status_filter, booking_id)
        data = [_serialize_obj(i) for i in invoices] if invoices else []
        # default=str is a final safety net for any edge-case types
        await redis.setex(key, CACHE_TTL, json.dumps(data, default=str))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write invoice cache: {e}")


async def invalidate_invoice_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"invoices:tenant_{tenant_id}:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate invoice cache: {e}")
