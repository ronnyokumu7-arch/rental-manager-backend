import json
import logging
from typing import Optional, Any, List
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 300


async def get_cached_investor_contract_list(
    tenant_id: int,
    vehicle_id: Optional[int] = None,
    contract_status: Optional[str] = None
) -> Optional[List[dict]]:
    """Fetch investor contracts from Redis cache."""
    redis = await get_redis()
    if not redis:
        return None

    try:
        key = f"investor_contracts:tenant_{tenant_id}:vehicle_{vehicle_id or 'all'}:status_{contract_status or 'all'}"
        cached = await redis.get(key)
        return deserialize_cache_list(cached) if cached else None
    except Exception as e:
        logger.warning(f"️ Failed to read investor contract cache: {e}")
        return None


async def set_cached_investor_contract_list(
    tenant_id: int,
    vehicle_id: Optional[int] = None,
    contract_status: Optional[str] = None,
    contracts: Optional[List[Any]] = None
) -> None:
    """Store investor contracts in Redis cache."""
    redis = await get_redis()
    if not redis:
        return

    try:
        key = f"investor_contracts:tenant_{tenant_id}:vehicle_{vehicle_id or 'all'}:status_{contract_status or 'all'}"
        data = [serialize_cache_item(c) for c in contracts] if contracts else []
        await redis.setex(key, CACHE_TTL, json.dumps(data))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write investor contract cache: {e}")


async def invalidate_investor_contract_cache(tenant_id: int) -> None:
    """Clear all investor contract cache keys for a specific tenant."""
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"investor_contracts:tenant_{tenant_id}:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate investor contract cache: {e}")
