import json
from typing import Optional, Any, List
from fastapi_cache import FastAPICache

CACHE_TTL = 300
ACTIVITY_TTL = 120  # Shorter TTL for semi-real-time logs


def _build_cache_key(
    tenant_id: int,
    user_id: int,
    limit: int,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by_priority: bool = False,
) -> str:
    """
    ✅ Build a deterministic cache key that accounts for ALL filter parameters.
    This prevents stale data when users switch between "Today" / "Week" / "Month".
    """
    parts = [
        f"tenant_{tenant_id}",
        f"user_{user_id}",
        f"limit_{limit}",
        f"action_{action or 'all'}",
        f"target_{target_type or 'all'}",
        f"start_{start_date or 'all'}",
        f"end_{end_date or 'all'}",
        f"priority_{sort_by_priority}",
    ]
    return f"activity_logs:{':'.join(parts)}"


async def get_cached_activity_logs(
    tenant_id: int,
    user_id: int,
    limit: int,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by_priority: bool = False,
) -> Optional[List[dict]]:
    """
    ✅ Retrieve cached logs with full filter awareness.
    Returns serialized JSON to prevent MissingGreenlet (no ORM objects in cache).
    """
    try:
        cache_key = _build_cache_key(
            tenant_id, user_id, limit, action, target_type, start_date, end_date, sort_by_priority
        )
        cached = await FastAPICache.get_backend().redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception:
        # ✅ Graceful degradation: if cache fails, fall back to DB
        return None


async def set_cached_activity_logs(
    tenant_id: int,
    user_id: int,
    limit: int,
    logs: Optional[List[Any]] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by_priority: bool = False,
) -> None:
    """
    ✅ Store serialized logs in cache with full filter awareness.
    ⚠️ NEVER stores ORM objects (prevents async lazy-loading errors).
    """
    try:
        cache_key = _build_cache_key(
            tenant_id, user_id, limit, action, target_type, start_date, end_date, sort_by_priority
        )
        redis = FastAPICache.get_backend().redis
        
        # ✅ Serialize safely (strip ORM relationships)
        data = []
        if logs:
            for log in logs:
                if hasattr(log, 'model_dump'):
                    # Pydantic v2
                    data.append(log.model_dump())
                elif hasattr(log, 'dict'):
                    # Pydantic v1
                    data.append(log.dict())
                else:
                    # ORM object: manually extract safe, serializable fields
                    data.append({
                        "id": log.id,
                        "tenant_id": log.tenant_id,
                        "user_id": log.user_id,
                        "action": log.action,
                        "label": log.label,
                        "target_type": log.target_type,
                        "target_id": log.target_id,
                        "summary": log.summary,
                        "details": log.details,
                        "priority": log.priority,
                        "created_at": log.created_at.isoformat() if log.created_at else None,
                    })
        
        await redis.setex(cache_key, ACTIVITY_TTL, json.dumps(data))
    except Exception:
        # ✅ Logging is non-critical; fail silently
        pass


async def invalidate_activity_log_cache(tenant_id: int, user_id: Optional[int] = None) -> None:
    """
    ✅ Invalidate ALL activity-log cache keys for the tenant.

    The default dashboard feed is TENANT-WIDE (keys contain user_None),
    so a user-scoped pattern would miss it and serve stale feeds.
    Activity writes are low-frequency; wiping the tenant namespace is
    correct and cheap. `user_id` kept for signature compatibility.
    """
    try:
        redis = FastAPICache.get_backend().redis
        pattern = f"activity_logs:tenant_{tenant_id}:*"

        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass
