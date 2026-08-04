import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_invoice_list(tenant_id: int, status_filter: Optional[str] = None, booking_id: Optional[int] = None) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"invoices:tenant_{tenant_id}:status_{status_filter or 'all'}:booking_{booking_id or 'all'}"
        cached = await redis.get(key)
        return json.loads(cached) if cached else None
    except Exception: return None

async def set_cached_invoice_list(tenant_id: int, status_filter: Optional[str] = None, booking_id: Optional[int] = None, invoices: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        key = f"invoices:tenant_{tenant_id}:status_{status_filter or 'all'}:booking_{booking_id or 'all'}"
        data = [i.model_dump() if hasattr(i, 'model_dump') else i for i in invoices] if invoices else []
        await redis.setex(key, CACHE_TTL, json.dumps(data))
    except Exception: pass

async def invalidate_invoice_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"invoices:tenant_{tenant_id}:*", count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception: pass
