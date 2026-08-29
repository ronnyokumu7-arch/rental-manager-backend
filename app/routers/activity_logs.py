from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.activity_log import ActivityLog
from app.models.users import User, UserRole
from app.schemas.activity_log import ActivityLogOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import get_cached_activity_logs, set_cached_activity_logs

router = APIRouter(prefix="/activity-logs", tags=["activity_logs"])

MAX_LOG_LIMIT = 100
DEFAULT_LOG_LIMIT = 50


@router.get("/", response_model=PaginatedResponse[ActivityLogOut])
@limiter.limit("60/minute")
async def get_activity_logs(
    request: Request,
    user_id: Optional[int] = Query(None, description="Filter by specific user ID (admin only)"),
    action: Optional[str] = Query(None, description="Filter by specific action (e.g., 'payment_received')"),
    target_type: Optional[str] = Query(None, description="Filter by target type (e.g., 'booking', 'vehicle')"),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering"),
    sort_by_priority: bool = Query(False, description="Sort by priority (critical first)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get activity logs with strict tenant isolation.
    
    ✅ SECURITY RULES:
    - Tenant users can ONLY see logs from their own tenant
    - Super admins can view logs for any user across all tenants
    
    ✅ ENHANCED FEATURES:
    - Time-range filtering (Today, This Week, This Month)
    - Action/Target Type filtering (Financials vs Dashboard distinction)
    - Priority sorting (Critical alerts on top)
    """
    page_size = min(max(page_size, 1), MAX_LOG_LIMIT)
    
    target_user_id = current_user.id
    
    if user_id is not None:
        if current_user.role == UserRole.super_admin:
            target_user_id = user_id
        else:
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
    
    # ✅ Build the base query with strict tenant isolation
    if current_user.role == UserRole.super_admin and user_id is not None:
        stmt = select(ActivityLog).where(ActivityLog.user_id == target_user_id)
    else:
        stmt = select(ActivityLog).where(
            ActivityLog.tenant_id == current_user.tenant_id,
            ActivityLog.user_id == target_user_id,
        )
    
    # ✅ Apply action filter (e.g., only payments/invoices for financials page)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    
    # ✅ Apply target type filter (e.g., only bookings, vehicles)
    if target_type:
        stmt = stmt.where(ActivityLog.target_type == target_type)
    
    # ✅ Apply time-range filters (for Today/Week/Month)
    if start_date:
        stmt = stmt.where(ActivityLog.created_at >= start_date)
    if end_date:
        stmt = stmt.where(ActivityLog.created_at <= end_date)
    
    # ✅ Apply priority sorting (critical alerts first, then newest)
    if sort_by_priority:
        stmt = stmt.order_by(ActivityLog.priority.desc(), ActivityLog.created_at.desc())
    else:
        stmt = stmt.order_by(ActivityLog.created_at.desc())
    
    # ✅ Fetch total count for pagination
    count_stmt = select(ActivityLog.id).where(
        ActivityLog.tenant_id == current_user.tenant_id,
        ActivityLog.user_id == target_user_id,
    )
    if action:
        count_stmt = count_stmt.where(ActivityLog.action == action)
    if target_type:
        count_stmt = count_stmt.where(ActivityLog.target_type == target_type)
    if start_date:
        count_stmt = count_stmt.where(ActivityLog.created_at >= start_date)
    if end_date:
        count_stmt = count_stmt.where(ActivityLog.created_at <= end_date)
    
    total_result = await db.execute(count_stmt)
    total = len(total_result.scalars().all())
    
    # ✅ Paginate
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    # ✅ FIXED: Manually serialize to ensure label, summary, priority are present
    serialized_logs = []
    for log in logs:
        log_data = ActivityLogOut.model_validate(log)
        # ✅ Ensure fields are populated (in case DB migration hasn't run)
        log_data.label = log_data.label or log.action.replace("_", " ").title()
        log_data.summary = log_data.summary or {}
        log_data.priority = log_data.priority or 2
        serialized_logs.append(log_data)
    
    # ✅ Return properly paginated response
    return paginate_items(
        serialized_logs,
        total=total,
        page=page,
        page_size=page_size,
    )
