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
    tenant_id: Optional[int], 
    status_filter: Optional[str], 
    vehicle_id: Optional[int], 
    client_id: Optional[int], 
    archived: bool
) -> str:
    return f"bookings:tenant_{tenant_id}:status_{status_filter or 'all'}:vehicle_{vehicle_id or 'all'}:client_{client_id or 'all'}:archived_{archived}"


async def get_cached_booking_list(
    tenant_id: Optional[int], 
    status_filter: Optional[str] = None, 
    vehicle_id: Optional[int] = None, 
    client_id: Optional[int] = None,
    archived: Optional[bool] = False
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cache_key = _build_cache_key(tenant_id, status_filter, vehicle_id, client_id, archived)
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read booking cache: {e}")
        return None


async def set_cached_booking_list(
    tenant_id: Optional[int], 
    status_filter: Optional[str] = None, 
    vehicle_id: Optional[int] = None, 
    client_id: Optional[int] = None,
    archived: Optional[bool] = False,
    bookings: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cache_key = _build_cache_key(tenant_id, status_filter, vehicle_id, client_id, archived)
        data = [_serialize_obj(b) for b in bookings] if bookings else []
        # default=str is a final safety net for any edge-case types
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data, default=str))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write booking cache: {e}")


async def invalidate_booking_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"bookings:tenant_{tenant_id}:*", count=100)
            if keys: 
                await redis.delete(*keys)
            if cursor == 0: 
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate booking cache: {e}")
