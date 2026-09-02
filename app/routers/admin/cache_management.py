# app/routers/admin/cache_management.py
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.limiter import limiter
from app.core.redis_client import get_redis
from app.dependencies.auth import require_super_admin
from app.models.users import User

router = APIRouter(prefix="/cache", tags=["Admin - Cache Management"])


@router.post("/flush", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")  # 🚨 STRICT: Only 5 flushes per minute
async def flush_all_cache(
    request: Request,
    current_user: User = Depends(require_super_admin),
):
    """
    🚨 SUPER ADMIN ONLY: Flush all application caches.
    
    Use this to clear poisoned cache data or force fresh data from the DB.
    Does NOT delete session tokens or auth data — only application caches.
    """
    redis = await get_redis()
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable"
        )
    
    # Flush only app-specific cache keys (not session/auth data)
    patterns = [
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
    
    deleted_count = 0
    for pattern in patterns:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                deleted_count += len(keys)
            if cursor == 0:
                break
    
    return {"message": f"Flushed {deleted_count} cache keys"}


@router.post("/flush/{resource}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def flush_resource_cache(
    request: Request,
    resource: str,
    current_user: User = Depends(require_super_admin),
):
    """
    🚨 SUPER ADMIN ONLY: Flush cache for a specific resource.
    
    Valid resources: clients, vehicles, bookings, contracts, invoices, 
                     payments, tasks, users, tenants, subscription, activity_logs
    """
    allowed_resources = {
        "clients", "vehicles", "bookings", "contracts", "invoices",
        "payments", "tasks", "users", "tenants", "subscription", "activity_logs"
    }
    
    if resource not in allowed_resources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource. Must be one of: {', '.join(sorted(allowed_resources))}"
        )
    
    redis = await get_redis()
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable"
        )
    
    pattern = f"{resource}:*"
    cursor = 0
    deleted_count = 0
    
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            await redis.delete(*keys)
            deleted_count += len(keys)
        if cursor == 0:
            break
    
    return {"message": f"Flushed {deleted_count} {resource} cache keys"}
