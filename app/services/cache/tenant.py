import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 60  # Short TTL for tenant list due to sensitivity

async def get_cached_tenant_list(
    skip: int,
    limit: int,
    search: Optional[str],
    status_filter: Optional[str],
    show_archived: bool,
) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = f"tenants:list:skip_{skip}:limit_{limit}:search_{search or 'none'}:status_{status_filter or 'all'}:archived_{show_archived}"
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception:
        return None

async def set_cached_tenant_list(
    skip: int,
    limit: int,
    search: Optional[str],
    status_filter: Optional[str],
    show_archived: bool,
    tenants: Optional[List[Any]] = None,
) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = f"tenants:list:skip_{skip}:limit_{limit}:search_{search or 'none'}:status_{status_filter or 'all'}:archived_{show_archived}"
        data = [t.model_dump() if hasattr(t, 'model_dump') else t for t in tenants] if tenants else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
    except Exception:
        pass

async def invalidate_tenant_cache() -> None:
    """Invalidates all tenant list caches. Call after any tenant mutation."""
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match="tenants:list:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass
