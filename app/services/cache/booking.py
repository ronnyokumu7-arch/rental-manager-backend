import json
import logging
from typing import Optional, Any, List
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 300


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
        return deserialize_cache_list(cached) if cached else None
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
        data = [serialize_cache_item(b) for b in bookings] if bookings else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
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
