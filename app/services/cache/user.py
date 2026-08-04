import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 120

async def get_cached_user_list(
    tenant_id: int, 
    role: Optional[str] = None, 
    is_active: Optional[bool] = None,
    is_suspended: Optional[bool] = None  # ✅ ADDED: to match router arguments
) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = (
            f"users:tenant_{tenant_id}:"
            f"role_{role or 'all'}:"
            f"active_{is_active if is_active is not None else 'all'}:"
            f"suspended_{is_suspended if is_suspended is not None else 'all'}"
        )
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception:
        return None

async def set_cached_user_list(
    tenant_id: int, 
    role: Optional[str] = None, 
    is_active: Optional[bool] = None,
    is_suspended: Optional[bool] = None,  # ✅ ADDED: to match router arguments
    users: Optional[List[Any]] = None
) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = (
            f"users:tenant_{tenant_id}:"
            f"role_{role or 'all'}:"
            f"active_{is_active if is_active is not None else 'all'}:"
            f"suspended_{is_suspended if is_suspended is not None else 'all'}"
        )
        data = [u.model_dump() if hasattr(u, 'model_dump') else u for u in users] if users else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
    except Exception:
        pass

async def invalidate_user_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        pattern = f"users:tenant_{tenant_id}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys: 
                await redis.delete(*keys)
            if cursor == 0: 
                break
    except Exception:
        pass
