import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_client_list(tenant_id: Optional[int], archived: bool = False) -> Optional[List[dict]]:
    try:
        cached = await FastAPICache.get_backend().redis.get(f"clients:tenant_{tenant_id}:archived_{archived}")
        return json.loads(cached) if cached else None
    except Exception: return None

async def set_cached_client_list(tenant_id: Optional[int], archived: bool = False, clients: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        data = [c.model_dump() if hasattr(c, 'model_dump') else c for c in clients] if clients else []
        await redis.setex(f"clients:tenant_{tenant_id}:archived_{archived}", CACHE_TTL, json.dumps(data))
    except Exception: pass

async def invalidate_client_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"clients:tenant_{tenant_id}:*", count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception: pass
