import json
import logging
from typing import Optional, Any, List
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 300


def _build_cache_key(
    tenant_id: int,
    invoice_id: Optional[int],
    status_filter: Optional[str],
    method_filter: Optional[str],
) -> str:
    return f"payments:tenant_{tenant_id}:invoice_{invoice_id or 'all'}:status_{status_filter or 'all'}:method_{method_filter or 'all'}"


async def get_cached_payment_list(
    tenant_id: int,
    invoice_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    method_filter: Optional[str] = None
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        key = _build_cache_key(tenant_id, invoice_id, status_filter, method_filter)
        cached = await redis.get(key)
        return deserialize_cache_list(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read payment cache: {e}")
        return None


async def set_cached_payment_list(
    tenant_id: int,
    invoice_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    method_filter: Optional[str] = None,
    payments: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        key = _build_cache_key(tenant_id, invoice_id, status_filter, method_filter)
        data = [serialize_cache_item(p) for p in payments] if payments else []
        await redis.setex(key, CACHE_TTL, json.dumps(data))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write payment cache: {e}")


async def invalidate_payment_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"payments:tenant_{tenant_id}:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate payment cache: {e}")
