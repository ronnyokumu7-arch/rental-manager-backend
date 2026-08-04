import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300
ACTIVITY_TTL = 120  # Shorter TTL for semi-real-time logs

async def get_cached_activity_logs(tenant_id: int, user_id: int, limit: int) -> Optional[List[dict]]:
    try:
        cached = await FastAPICache.get_backend().redis.get(f"activity_logs:tenant_{tenant_id}:user_{user_id}:limit_{limit}")
        return json.loads(cached) if cached else None
    except Exception: return None

async def set_cached_activity_logs(tenant_id: int, user_id: int, limit: int, logs: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        data = [log.model_dump() if hasattr(log, 'model_dump') else log for log in logs] if logs else []
        await redis.setex(f"activity_logs:tenant_{tenant_id}:user_{user_id}:limit_{limit}", ACTIVITY_TTL, json.dumps(data))
    except Exception: pass

async def invalidate_activity_log_cache(tenant_id: int, user_id: Optional[int] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        pattern = f"activity_logs:tenant_{tenant_id}:user_{user_id}:*" if user_id else f"activity_logs:tenant_{tenant_id}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception: pass
