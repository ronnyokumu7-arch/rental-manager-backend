from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.activity_log import ActivityLog
from app.models.users import User, UserRole
from app.schemas.activity_log import ActivityLogOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import get_cached_activity_logs, set_cached_activity_logs

router = APIRouter(prefix="/activity-logs", tags=["activity_logs"])

# ✅ Maximum logs per request to prevent abuse
MAX_LOG_LIMIT = 100
DEFAULT_LOG_LIMIT = 50


@router.get("/", response_model=PaginatedResponse[ActivityLogOut])
@limiter.limit("60/minute")
async def get_activity_logs(
    request: Request,
    user_id: Optional[int] = Query(None, description="Filter by specific user ID (admin only)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT, description="Number of logs to return (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get activity logs with strict tenant isolation.
    
    ✅ SECURITY RULES:
    - Tenant users can ONLY see logs from their own tenant
    - If user_id is provided, tenant users can only view logs for users in their tenant
    - If no user_id is provided, defaults to current user's logs
    - Super admins can view logs for any user across all tenants
    
    ✅ PERFORMANCE: Results are cached for 2 minutes (read-heavy endpoint).
    """
    # ✅ Enforce page size bounds (defense in depth — Pydantic also validates)
    page_size = min(max(page_size, 1), MAX_LOG_LIMIT)
    
    # Determine which user's logs to fetch
    target_user_id = current_user.id
    
    if user_id is not None:
        if current_user.role == UserRole.super_admin:
            # ✅ Super admin bypass — can view any user's logs
            target_user_id = user_id
        else:
            # ✅ CRITICAL: Verify target user belongs to current tenant
            target_stmt = select(User).where(
                User.id == user_id,
                User.tenant_id == current_user.tenant_id,
            )
            target_result = await db.execute(target_stmt)
            target_user = target_result.scalars().first()
            
            if not target_user:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: user not found in your tenant",
                )
            target_user_id = user_id
    
    # ✅ Check cache first (keyed by tenant + user + limit)
    cached = await get_cached_activity_logs(
        tenant_id=current_user.tenant_id,
        user_id=target_user_id,
        limit=page_size,
    )
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)
    
    # ✅ CRITICAL: ALWAYS scope to tenant_id (prevents cross-tenant leaks)
    if current_user.role == UserRole.super_admin and user_id is not None:
        # Super admin viewing specific user — no tenant filter needed
        stmt = select(ActivityLog).where(ActivityLog.user_id == target_user_id)
    else:
        # Everyone else — MUST be tenant-scoped
        stmt = select(ActivityLog).where(
            ActivityLog.tenant_id == current_user.tenant_id,
            ActivityLog.user_id == target_user_id,
        )
    
    stmt = stmt.order_by(ActivityLog.created_at.desc())
    result = await db.execute(stmt)
    logs = result.scalars().all()
    
    # ✅ Write to cache (2-minute TTL — activity logs are semi-real-time)
    await set_cached_activity_logs(
        tenant_id=current_user.tenant_id,
        user_id=target_user_id,
        limit=page_size,
        logs=logs,
    )
    
    return paginate_items(logs, total=len(logs), page=page, page_size=page_size)
