import json
import logging
from typing import Optional, Any, List
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 300


async def get_cached_client_list(
    tenant_id: Optional[int],
    archived: bool = False
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cached = await redis.get(f"clients:tenant_{tenant_id}:archived_{archived}")
        return deserialize_cache_list(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read client cache: {e}")
        return None


async def set_cached_client_list(
    tenant_id: Optional[int],
    archived: bool = False,
    clients: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        data = [serialize_cache_item(c) for c in clients] if clients else []
        await redis.setex(
            f"clients:tenant_{tenant_id}:archived_{archived}",
            CACHE_TTL,
            json.dumps(data)
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to write client cache: {e}")


async def invalidate_client_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"clients:tenant_{tenant_id}:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate client cache: {e}")
