import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_booking_list(
    tenant_id: Optional[int], 
    status_filter: Optional[str] = None, 
    vehicle_id: Optional[int] = None, 
    client_id: Optional[int] = None,
    archived: Optional[bool] = False  # ✅ ADDED: to match router arguments
) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = f"bookings:tenant_{tenant_id}:status_{status_filter or 'all'}:vehicle_{vehicle_id or 'all'}:client_{client_id or 'all'}:archived_{archived}"
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception:
        return None

async def set_cached_booking_list(
    tenant_id: Optional[int], 
    status_filter: Optional[str] = None, 
    vehicle_id: Optional[int] = None, 
    client_id: Optional[int] = None,
    archived: Optional[bool] = False,  # ✅ ADDED: to match router arguments
    bookings: Optional[List[Any]] = None
) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = f"bookings:tenant_{tenant_id}:status_{status_filter or 'all'}:vehicle_{vehicle_id or 'all'}:client_{client_id or 'all'}:archived_{archived}"
        data = [b.model_dump() if hasattr(b, 'model_dump') else b for b in bookings] if bookings else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
    except Exception:
        pass

async def invalidate_booking_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            # This wildcard pattern automatically catches the new 'archived' variations
            cursor, keys = await redis.scan(cursor=cursor, match=f"bookings:tenant_{tenant_id}:*", count=100)
            if keys: 
                await redis.delete(*keys)
            if cursor == 0: 
                break
    except Exception:
        pass
