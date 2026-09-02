# app/routers/admin.py

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.core.redis_client import get_redis
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.jobs.booking_jobs import run_booking_auto_archive
from app.jobs.subscription_jobs import run_subscription_lifecycle
from app.models.users import User, UserRole
from app.models.subscriptions import Subscription 
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/admin", tags=["admin"])

# Dependency for cleaner code
super_admin_only = Depends(require_role([UserRole.super_admin]))

# --- Subscription Endpoints ---

@router.get("/subscriptions/pending")
@limiter.limit("20/minute")
async def get_pending_subscriptions(
    request: Request,
    current_user: User = super_admin_only,
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch all subscriptions awaiting approval.
    """
    try:
        stmt = select(Subscription).where(Subscription.status == "pending")
        result = await db.execute(stmt)
        pending = result.scalars().all()
        return pending
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch subscriptions: {str(e)}")

# --- Job Trigger Endpoints ---

@router.post("/jobs/run-subscription-lifecycle")
@limiter.limit("5/minute")
async def trigger_subscription_lifecycle(
    request: Request,
    current_user: User = super_admin_only,
    db: AsyncSession = Depends(get_db)
):
    await run_subscription_lifecycle()
    
    await ActivityLogService.log(
        db=db, tenant_id=0, user_id=current_user.id,
        action="trigger_subscription_lifecycle", target_type="system", target_id=0,
        details={"triggered_by": current_user.full_name}
    )
    await db.commit()
    
    return {"message": "Subscription lifecycle job completed"}

@router.post("/jobs/run-booking-archive")
@limiter.limit("5/minute")
async def trigger_booking_archive(
    request: Request,
    current_user: User = super_admin_only,
    db: AsyncSession = Depends(get_db)
):
    await run_booking_auto_archive()
    
    await ActivityLogService.log(
        db=db, tenant_id=0, user_id=current_user.id,
        action="trigger_booking_archive", target_type="system", target_id=0,
        details={"triggered_by": current_user.full_name}
    )
    await db.commit()
    
    return {"message": "Booking auto-archive job completed"}


# --- Cache Management Endpoints ---

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


@router.post("/cache/flush", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
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


@router.post("/cache/flush/{resource}", status_code=status.HTTP_200_OK)
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
