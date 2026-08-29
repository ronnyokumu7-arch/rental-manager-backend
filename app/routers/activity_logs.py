from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func
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

router = APIRouter(
    prefix="/activity-logs",
    tags=["activity_logs"],
    redirect_slashes=False,  # ✅ Prevents 307 redirect
)

MAX_LOG_LIMIT = 100
DEFAULT_LOG_LIMIT = 50


@router.get("/", response_model=PaginatedResponse[ActivityLogOut])
@limiter.limit("60/minute")
async def get_activity_logs(
    request: Request,
    user_id: Optional[int] = Query(None, description="Filter by specific user ID (personal/audit view)"),
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

    ✅ FEED SEMANTICS:
    - DEFAULT (no user_id): TENANT-WIDE feed — all staff actions + system/scheduler
      alerts (user_id IS NULL). This is what the dashboard expects.
    - With user_id: personal/audit view for that user (permission-checked).
    - Super admin + user_id: cross-tenant view of that user.
    """
    page_size = min(max(page_size, 1), MAX_LOG_LIMIT)

    # ── Resolve scope ──────────────────────────────────────────────────────
    filters = []
    if user_id is not None:
        # Explicit personal/audit view — permission-checked
        if current_user.role != UserRole.super_admin:
            target_stmt = select(User).where(
                User.id == user_id,
                User.tenant_id == current_user.tenant_id,
            )
            target_result = await db.execute(target_stmt)
            if not target_result.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: user not found in your tenant",
                )
            filters.append(ActivityLog.tenant_id == current_user.tenant_id)
        filters.append(ActivityLog.user_id == user_id)
    elif current_user.role != UserRole.super_admin:
        # ✅ DEFAULT: tenant-wide feed (all users + system events)
        filters.append(ActivityLog.tenant_id == current_user.tenant_id)
    # super admin without user_id → platform-wide view (no filters)

    # ── Optional dimension filters ─────────────────────────────────────────
    if action:
        filters.append(ActivityLog.action == action)
    if target_type:
        filters.append(ActivityLog.target_type == target_type)
    if start_date:
        filters.append(ActivityLog.created_at >= start_date)
    if end_date:
        filters.append(ActivityLog.created_at <= end_date)

    # ── Data query ─────────────────────────────────────────────────────────
    stmt = select(ActivityLog).where(*filters)
    if sort_by_priority:
        stmt = stmt.order_by(ActivityLog.priority.desc(), ActivityLog.created_at.desc())
    else:
        stmt = stmt.order_by(ActivityLog.created_at.desc())

    # ── Total count (same filters, no ordering) ────────────────────────────
    count_stmt = select(func.count()).select_from(ActivityLog).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    # ── Paginate ───────────────────────────────────────────────────────────
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    # ✅ Manually serialize to ensure label, summary, priority are present
    serialized_logs = []
    for log in logs:
        log_data = ActivityLogOut.model_validate(log)
        log_data.label = log_data.label or log.action.replace("_", " ").title()
        log_data.summary = log_data.summary or {}
        log_data.priority = log_data.priority or 2
        serialized_logs.append(log_data)

    return paginate_items(
        serialized_logs,
        total=total,
        page=page,
        page_size=page_size,
    )
