import json
import logging
from typing import Optional, Any, List
from datetime import datetime, date
from decimal import Decimal

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 60  # Short TTL for tenant list due to sensitivity


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
    skip: int,
    limit: int,
    search: Optional[str],
    status_filter: Optional[str],
    show_archived: bool,
) -> str:
    return f"tenants:list:skip_{skip}:limit_{limit}:search_{search or 'none'}:status_{status_filter or 'all'}:archived_{show_archived}"


async def get_cached_tenant_list(
    skip: int,
    limit: int,
    search: Optional[str],
    status_filter: Optional[str],
    show_archived: bool,
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cache_key = _build_cache_key(skip, limit, search, status_filter, show_archived)
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read tenant cache: {e}")
        return None


async def set_cached_tenant_list(
    skip: int,
    limit: int,
    search: Optional[str],
    status_filter: Optional[str],
    show_archived: bool,
    tenants: Optional[List[Any]] = None,
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cache_key = _build_cache_key(skip, limit, search, status_filter, show_archived)
        data = [_serialize_obj(t) for t in tenants] if tenants else []
        # default=str is a final safety net for any edge-case types
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data, default=str))
    except Exception as e:
        logger.warning(f"⚠️ Failed to write tenant cache: {e}")


async def invalidate_tenant_cache() -> None:
    """Invalidates all tenant list caches. Call after any tenant mutation."""
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match="tenants:list:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate tenant cache: {e}")
