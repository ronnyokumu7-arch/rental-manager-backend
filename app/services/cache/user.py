import json
import logging
from typing import Optional, Any, List
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 120


def _build_cache_key(
    tenant_id: int,
    role: Optional[str],
    is_active: Optional[bool],
    is_suspended: Optional[bool],
) -> str:
    return (
        f"users:tenant_{tenant_id}:"
        f"role_{role or 'all'}:"
        f"active_{is_active if is_active is not None else 'all'}:"
        f"suspended_{is_suspended if is_suspended is not None else 'all'}"
    )


async def get_cached_user_list(
    tenant_id: int, 
    role: Optional[str] = None, 
    is_active: Optional[bool] = None,
    is_suspended: Optional[bool] = None
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cache_key = _build_cache_key(tenant_id, role, is_active, is_suspended)
        cached = await redis.get(cache_key)
        return deserialize_cache_list(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read user cache: {e}")
        return None


async def set_cached_user_list(
    tenant_id: int, 
    role: Optional[str] = None, 
    is_active: Optional[bool] = None,
    is_suspended: Optional[bool] = None,
    users: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cache_key = _build_cache_key(tenant_id, role, is_active, is_suspended)
        data = [serialize_cache_item(u) for u in users] if users else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write user cache: {e}")


async def invalidate_user_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        pattern = f"users:tenant_{tenant_id}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys: 
                await redis.delete(*keys)
            if cursor == 0: 
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate user cache: {e}")
