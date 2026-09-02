import json
import logging
from typing import Optional, Any, List
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 120


def _scope_key(tenant_id: Optional[int]) -> str:
    return f"tenant_{tenant_id}" if tenant_id is not None else "platform"


def _build_cache_key(
    tenant_id: Optional[int],
    user_id: Optional[int],
    status: Optional[str],
    category: Optional[str],
) -> str:
    return f"tasks:{_scope_key(tenant_id)}:user_{user_id or 'all'}:status_{status or 'all'}:category_{category or 'all'}"


async def get_cached_task_list(
    tenant_id: Optional[int],
    user_id: Optional[int],
    status: Optional[str],
    category: Optional[str]
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cache_key = _build_cache_key(tenant_id, user_id, status, category)
        cached = await redis.get(cache_key)
        return deserialize_cache_list(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read task cache: {e}")
        return None


async def set_cached_task_list(
    tenant_id: Optional[int],
    user_id: Optional[int],
    status: Optional[str],
    category: Optional[str],
    tasks: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cache_key = _build_cache_key(tenant_id, user_id, status, category)
        data = [serialize_cache_item(t) for t in tasks] if tasks else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write task cache: {e}")


async def invalidate_task_cache(tenant_id: Optional[int] = None, user_id: Optional[int] = None) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        scope = _scope_key(tenant_id) if tenant_id is not None else "*"
        pattern = f"tasks:{scope}:user_{user_id or '*'}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate task cache: {e}")
