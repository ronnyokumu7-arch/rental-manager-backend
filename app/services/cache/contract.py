import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_contract_list(tenant_id: int, booking_id: Optional[int] = None, contract_status: Optional[str] = None) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"contracts:tenant_{tenant_id}:booking_{booking_id or 'all'}:status_{contract_status or 'all'}"
        cached = await redis.get(key)
        return json.loads(cached) if cached else None
    except Exception: return None

async def set_cached_contract_list(tenant_id: int, booking_id: Optional[int] = None, contract_status: Optional[str] = None, contracts: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"contracts:tenant_{tenant_id}:booking_{booking_id or 'all'}:status_{contract_status or 'all'}"
        data = [c.model_dump() if hasattr(c, 'model_dump') else c for c in contracts] if contracts else []
        await redis.setex(key, CACHE_TTL, json.dumps(data))
    except Exception: pass

async def invalidate_contract_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"contracts:tenant_{tenant_id}:*", count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception: pass
