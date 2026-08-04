# app/routers/admin.py

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   #  Rate limiter for admin actions
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
@limiter.limit("20/minute")  # 🚨 Protects against scraping or accidental spam
async def get_pending_subscriptions(
    request: Request,
    current_user: User = super_admin_only,
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch all subscriptions awaiting approval.
    Matches path: /api/v1/admin/subscriptions/pending
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
@limiter.limit("5/minute")  # 🚨 STRICT: Job triggers should be heavily limited
async def trigger_subscription_lifecycle(
    request: Request,
    current_user: User = super_admin_only,
    db: AsyncSession = Depends(get_db)
):
    await run_subscription_lifecycle()
    
    # ✅ Log the job trigger for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=0, user_id=current_user.id,
        action="trigger_subscription_lifecycle", target_type="system", target_id=0,
        details={"triggered_by": current_user.full_name}
    )
    await db.commit()  # Commit the activity log flush
    
    return {"message": "Subscription lifecycle job completed"}

@router.post("/jobs/run-booking-archive")
@limiter.limit("5/minute")  #  STRICT: Job triggers should be heavily limited
async def trigger_booking_archive(
    request: Request,
    current_user: User = super_admin_only,
    db: AsyncSession = Depends(get_db)
):
    await run_booking_auto_archive()
    
    # ✅ Log the job trigger for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=0, user_id=current_user.id,
        action="trigger_booking_archive", target_type="system", target_id=0,
        details={"triggered_by": current_user.full_name}
    )
    await db.commit()  # Commit the activity log flush
    
    return {"message": "Booking auto-archive job completed"}
