import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_vehicle_list(tenant_id: Optional[int], archived: bool = False, status_filter: Optional[str] = None) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"vehicles:tenant_{tenant_id}:archived_{archived}" + (f":status_{status_filter}" if status_filter else "")
        cached = await redis.get(key)
        return json.loads(cached) if cached else None
    except Exception: return None

async def set_cached_vehicle_list(tenant_id: Optional[int], archived: bool = False, status_filter: Optional[str] = None, vehicles: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"vehicles:tenant_{tenant_id}:archived_{archived}" + (f":status_{status_filter}" if status_filter else "")
        data = [v.model_dump() if hasattr(v, 'model_dump') else v for v in vehicles] if vehicles else []
        await redis.setex(key, CACHE_TTL, json.dumps(data))
    except Exception: pass

async def invalidate_vehicle_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"vehicles:tenant_{tenant_id}:*", count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception: pass
