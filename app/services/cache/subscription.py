import json
from typing import Optional
from fastapi_cache import FastAPICache

CACHE_TTL = 300

async def get_cached_subscription_status(tenant_id: int) -> Optional[str]:
    try:
        cached = await FastAPICache.get_backend().redis.get(f"subscription:status:tenant_{tenant_id}")
        return json.loads(cached) if cached else None
    except Exception: 
        return None

async def set_cached_subscription_status(tenant_id: int, status_value: str) -> None:
    try:
        await FastAPICache.get_backend().redis.setex(f"subscription:status:tenant_{tenant_id}", CACHE_TTL, json.dumps(status_value))
    except Exception: 
        pass

async def get_cached_subscription_warning(tenant_id: int) -> Optional[dict]:
    try:
        cached = await FastAPICache.get_backend().redis.get(f"subscription:warning:tenant_{tenant_id}")
        return json.loads(cached) if cached else None
    except Exception: 
        return None

async def set_cached_subscription_warning(tenant_id: int, warning: Optional[dict]) -> None:
    try:
        await FastAPICache.get_backend().redis.setex(f"subscription:warning:tenant_{tenant_id}", CACHE_TTL, json.dumps(warning or {}))
    except Exception: 
        pass

async def invalidate_subscription_cache(tenant_id: int) -> None:
    try:
        redis = FastAPICache.get_backend().redis
        await redis.delete(f"subscription:status:tenant_{tenant_id}", f"subscription:warning:tenant_{tenant_id}")
    except Exception: 
        pass
