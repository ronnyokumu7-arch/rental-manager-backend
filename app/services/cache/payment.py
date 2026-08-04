import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_payment_list(tenant_id: int, invoice_id: Optional[int] = None, status_filter: Optional[str] = None, method_filter: Optional[str] = None) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"payments:tenant_{tenant_id}:invoice_{invoice_id or 'all'}:status_{status_filter or 'all'}:method_{method_filter or 'all'}"
        cached = await redis.get(key)
        return json.loads(cached) if cached else None
    except Exception: return None

async def set_cached_payment_list(tenant_id: int, invoice_id: Optional[int] = None, status_filter: Optional[str] = None, method_filter: Optional[str] = None, payments: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"payments:tenant_{tenant_id}:invoice_{invoice_id or 'all'}:status_{status_filter or 'all'}:method_{method_filter or 'all'}"
        data = [p.model_dump() if hasattr(p, 'model_dump') else p for p in payments] if payments else []
        await redis.setex(key, CACHE_TTL, json.dumps(data))
    except Exception: pass

async def invalidate_payment_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"payments:tenant_{tenant_id}:*", count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception: pass
