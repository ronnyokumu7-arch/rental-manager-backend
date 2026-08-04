import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 120

def _scope_key(tenant_id: Optional[int]) -> str:
    return f"tenant_{tenant_id}" if tenant_id is not None else "platform"


async def get_cached_task_list(tenant_id: Optional[int], user_id: Optional[int], status: Optional[str], category: Optional[str]) -> Optional[List[dict]]:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = f"tasks:{_scope_key(tenant_id)}:user_{user_id or 'all'}:status_{status or 'all'}:category_{category or 'all'}"
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception:
        return None

async def set_cached_task_list(tenant_id: Optional[int], user_id: Optional[int], status: Optional[str], category: Optional[str], tasks: Optional[List[Any]] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        cache_key = f"tasks:{_scope_key(tenant_id)}:user_{user_id or 'all'}:status_{status or 'all'}:category_{category or 'all'}"
        data = [t.model_dump() if hasattr(t, 'model_dump') else t for t in tasks] if tasks else []
        await redis.setex(cache_key, CACHE_TTL, json.dumps(data))
    except Exception:
        pass

async def invalidate_task_cache(tenant_id: Optional[int] = None, user_id: Optional[int] = None) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        scope = _scope_key(tenant_id) if tenant_id is not None else "*"
        pattern = f"tasks:{scope}:user_{user_id or '*'}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys: await redis.delete(*keys)
            if cursor == 0: break
    except Exception:
        pass
