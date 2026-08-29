# app/routers/system.py

import os
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   #  Rate limiter
from app.models.users import User, UserRole
from app.services.daily_scheduler import DailySchedulerService
from app.core.config import get_settings
from app.services.activity_logs.service import ActivityLogService  # ✅ FIXED path

router = APIRouter(prefix="/system", tags=["system"])

# Load the secret from environment variables (Fallback for local dev)
CRON_SECRET = os.getenv("CRON_SECRET", "super-secret-cron-key-change-me-in-production")

async def verify_system_access(
    x_cron_secret: str = Header(None, alias="X-Cron-Secret"),
    authorization: str = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db)
):
    """
    DUAL-AUTH SECURITY:
    1. If triggered by a Cron Job, it must pass the X-Cron-Secret header.
    2. If triggered manually from the UI, the user MUST be a super_admin.
    """
    # ✅ PATH A: Automated Cron Job (Bypasses JWT entirely)
    if x_cron_secret == CRON_SECRET:
        return {"triggered_by": "cron_job", "user_id": None}

    # ✅ PATH B: Manual Admin Trigger (Requires JWT)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Requires Super Admin role or valid Cron Secret."
        )

    token = authorization.split(" ")[1]
    settings = get_settings()

    # Safely get secret key and algorithm from settings
    secret_key = getattr(settings, "SECRET_KEY", None) or getattr(settings, "secret_key", None)
    algorithm = getattr(settings, "ALGORITHM", None) or getattr(settings, "algorithm", "HS256")

    if not secret_key:
        raise HTTPException(status_code=500, detail="Server misconfiguration: Missing SECRET_KEY")

    try:
        # Try python-jose first (FastAPI standard), then fallback to PyJWT
        try:
            from jose import jwt, JWTError
            payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        except ImportError:
            import jwt
            payload = jwt.decode(token, secret_key, algorithms=[algorithm])

        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=403, detail="Invalid token payload")

        # ✅ ASYNC USER LOOKUP
        stmt = select(User).where(User.id == int(user_id))
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user or user.role != UserRole.super_admin:
            raise HTTPException(status_code=403, detail="Not authorized. Requires Super Admin role.")

        # ✅ UPDATED: Return user_id for activity logging
        return {"triggered_by": "super_admin", "user_id": user.id}

    except Exception:
        raise HTTPException(status_code=403, detail="Invalid token or unauthorized")

@router.post("/run-daily-tasks")
@limiter.limit("5/minute")  # 🚨 STRICT: System-wide task trigger
async def run_daily_tasks(
    request: Request,
    access: dict = Depends(verify_system_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually or automatically triggers the daily compliance and financial checks.
    """
    try:
        # ✅ FIXED: awaited — the coroutine actually runs now
        await DailySchedulerService.run_daily_checks(db)

        # ✅ FIXED: removed tenant_id=0 audit log — it violated the
        # activity_logs.tenant_id FK and rolled back the entire run.
        # (Cron triggers are audited via Render/cron logs + per-tenant alerts.)

        # ✅ Commit everything the scheduler flushed (tasks + activity logs)
        await db.commit()

        return {
            "message": "Daily tasks generated successfully",
            "details": access
        }
    except Exception as e:
        await db.rollback()  # ✅ don't leave a poisoned session
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scheduler failed: {str(e)}"
        )
