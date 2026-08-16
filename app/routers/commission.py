# app/routers/commission.py
from datetime import datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.commission import CommissionEvent, CommissionStatus
from app.models.users import User, UserRole
from app.schemas.commission import CommissionEventOut, CommissionSummaryOut

router = APIRouter(prefix="/commission")

# ✅ PLATFORM TIMEZONE: the commission day rolls over at 00:00H East Africa Time
PLATFORM_TZ = ZoneInfo("Africa/Nairobi")

# TODO: move to platform settings (super-admin configurable)
DEFAULT_GRACE_DAYS = 3


def _today_start() -> datetime:
    """00:00:00 today in platform timezone (timezone-aware)."""
    now = datetime.now(PLATFORM_TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _resolve_tenant(current_user: User, tenant_id: Optional[int]) -> int:
    """Tenants see only themselves; super admins may inspect any tenant."""
    if tenant_id is not None:
        if current_user.role != UserRole.super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super admins can inspect other tenants' commissions.",
            )
        return tenant_id
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant context for this account.",
        )
    return current_user.tenant_id


@router.get("/summary", response_model=CommissionSummaryOut)
@limiter.limit("30/minute")
async def commission_summary(
    request: Request,
    tenant_id: Optional[int] = Query(None, description="Super admin may inspect any tenant"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # ✅ Reads stay open even when soft-locked
):
    """
    ✅ The daily-resetting commission picture for the tenant dashboard.
    - today_* resets at 00:00H EAT
    - outstanding_* = unpaid balance from previous days (the "tag")
    - soft_locked drives the burner banner + operational block
    """
    target = _resolve_tenant(current_user, tenant_id)
    today_start = _today_start()

    # 1) Today's counter (resets at 00:00H)
    stmt_today = select(
        func.count(CommissionEvent.id),
        func.coalesce(func.sum(CommissionEvent.amount), 0),
    ).where(
        CommissionEvent.tenant_id == target,
        CommissionEvent.trip_started_at >= today_start,
    )
    today_count, today_total = (await db.execute(stmt_today)).one()

    # 2) Outstanding balance (previous days, still unpaid)
    stmt_out = select(
        func.count(CommissionEvent.id),
        func.coalesce(func.sum(CommissionEvent.amount), 0),
    ).where(
        CommissionEvent.tenant_id == target,
        CommissionEvent.status == CommissionStatus.unpaid,
        CommissionEvent.trip_started_at < today_start,
    )
    out_count, out_total = (await db.execute(stmt_out)).one()

    # 3) Oldest unpaid event → grace-period countdown
    stmt_old = select(func.min(CommissionEvent.trip_started_at)).where(
        CommissionEvent.tenant_id == target,
        CommissionEvent.status == CommissionStatus.unpaid,
    )
    oldest_unpaid_at = (await db.execute(stmt_old)).scalar_one_or_none()

    grace_days = DEFAULT_GRACE_DAYS
    days_until_lock: Optional[int] = None
    soft_locked = False

    if oldest_unpaid_at is not None:
        age_days = (
            datetime.now(PLATFORM_TZ).date()
            - oldest_unpaid_at.astimezone(PLATFORM_TZ).date()
        ).days
        days_until_lock = grace_days - age_days
        soft_locked = days_until_lock <= 0

    return CommissionSummaryOut(
        currency_code="KES",
        today_count=int(today_count),
        today_total=Decimal(today_total),
        outstanding_count=int(out_count),
        outstanding_balance=Decimal(out_total),
        oldest_unpaid_at=oldest_unpaid_at,
        grace_days=grace_days,
        days_until_lock=days_until_lock,
        soft_locked=soft_locked,
    )


@router.get("/events", response_model=list[CommissionEventOut])
@limiter.limit("30/minute")
async def commission_events(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    tenant_id: Optional[int] = Query(None, description="Super admin may inspect any tenant"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ The ledger history — the 'home' for every commission event."""
    target = _resolve_tenant(current_user, tenant_id)

    stmt = (
        select(CommissionEvent)
        .where(CommissionEvent.tenant_id == target)
        .order_by(CommissionEvent.trip_started_at.desc())
        .limit(limit)
    )
    events = (await db.execute(stmt)).scalars().all()
    return events
