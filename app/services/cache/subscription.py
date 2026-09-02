import json
import logging
from typing import Optional

from app.core.redis_client import get_redis
from app.services.cache.serialization import serialize_cache_item

logger = logging.getLogger(__name__)

CACHE_TTL = 300


async def get_cached_subscription_status(tenant_id: int) -> Optional[str]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cached = await redis.get(f"subscription:status:tenant_{tenant_id}")
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read subscription status cache: {e}")
        return None


async def set_cached_subscription_status(tenant_id: int, status_value: str) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        await redis.setex(
            f"subscription:status:tenant_{tenant_id}",
            CACHE_TTL,
            json.dumps(status_value)
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to write subscription status cache: {e}")


async def get_cached_subscription_warning(tenant_id: int) -> Optional[dict]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cached = await redis.get(f"subscription:warning:tenant_{tenant_id}")
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read subscription warning cache: {e}")
        return None


async def set_cached_subscription_warning(tenant_id: int, warning: Optional[dict]) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        await redis.setex(
            f"subscription:warning:tenant_{tenant_id}",
            CACHE_TTL,
            json.dumps(serialize_cache_item(warning or {}))
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to write subscription warning cache: {e}")


async def invalidate_subscription_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        await redis.delete(
            f"subscription:status:tenant_{tenant_id}",
            f"subscription:warning:tenant_{tenant_id}"
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate subscription cache: {e}")
