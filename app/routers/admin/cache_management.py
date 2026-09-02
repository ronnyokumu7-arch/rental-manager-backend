# app/routers/admin/cache_management.py
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.limiter import limiter
from app.core.redis_client import get_redis
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole

router = APIRouter(prefix="/cache", tags=["Admin - Cache Management"])

# ✅ Same dependency pattern as app/routers/admin.py
super_admin_only = Depends(require_role([UserRole.super_admin]))

CACHE_PATTERNS = [
    "clients:*",
    "vehicles:*",
    "bookings:*",
    "contracts:*",
    "invoices:*",
    "payments:*",
    "tasks:*",
    "users:*",
    "tenants:*",
    "subscription:*",
    "activity_logs:*",
]


async def _delete_pattern(redis, pattern: str) -> int:
    """Scan-and-delete all keys matching a pattern. Returns deleted count."""
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            await redis.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break
    return deleted


@router.post("/flush", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")  # 🚨 STRICT: flushes are heavy operations
async def flush_all_cache(
    request: Request,
    current_user: User = super_admin_only,
):
    """
    🚨 SUPER ADMIN ONLY: Flush all application caches.
    Clears poisoned/stale list caches so fresh data loads from the DB.
    """
    redis = await get_redis()
    if redis is None:
        return {"message": "Redis unavailable — nothing to flush", "deleted": 0}

    deleted_count = 0
    for pattern in CACHE_PATTERNS:
        deleted_count += await _delete_pattern(redis, pattern)

    return {"message": f"Flushed {deleted_count} cache keys", "deleted": deleted_count}


@router.post("/flush/{resource}", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def flush_resource_cache(
    request: Request,
    resource: str,
    current_user: User = super_admin_only,
):
    """
    🚨 SUPER ADMIN ONLY: Flush cache for a single resource.
    Valid: clients, vehicles, bookings, contracts, invoices, payments,
           tasks, users, tenants, subscription, activity_logs
    """
    allowed = {p[: -len(":*")] for p in CACHE_PATTERNS}
    if resource not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource. Must be one of: {', '.join(sorted(allowed))}",
        )

    redis = await get_redis()
    if redis is None:
        return {"message": "Redis unavailable — nothing to flush", "deleted": 0}

    deleted_count = await _delete_pattern(redis, f"{resource}:*")
    return {"message": f"Flushed {deleted_count} {resource} cache keys", "deleted": deleted_count}
