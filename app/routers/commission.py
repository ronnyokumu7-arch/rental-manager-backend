# app/routers/commission.py
from datetime import datetime, timezone
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
from app.models.commission_payment import CommissionPayment, CommissionPaymentStatus
from app.models.platform_settings import PlatformSettings
from app.models.users import User, UserRole
from app.schemas.platform_settings import PlatformSettingsOut, PlatformSettingsUpdate
from app.schemas.commission import CommissionEventOut, CommissionSummaryOut
from app.schemas.commission_payment import (
    CommissionPaymentCreate,
    CommissionPaymentInfoOut,
    CommissionPaymentOut,
    CommissionPaymentRejectIn,
    CommissionPaymentVerifyResult,
)

router = APIRouter(prefix="/commission")

# ✅ PLATFORM TIMEZONE: the commission day rolls over at 00:00H East Africa Time
PLATFORM_TZ = ZoneInfo("Africa/Nairobi")

# Fallback if the singleton row is ever missing (should never happen — seeded)
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


async def _get_settings(db: AsyncSession) -> Optional[PlatformSettings]:
    """Fetch the platform settings singleton (id=1)."""
    return (
        await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    ).scalars().first()


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

    # ✅ Grace days now come from PlatformSettings (super-admin configurable)
    settings = await _get_settings(db)
    grace_days = settings.grace_period_days if settings else DEFAULT_GRACE_DAYS

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


# ---------------------------------------------------------------------------
# PAYMENT COLLECTION (tenant pays the platform)
# ---------------------------------------------------------------------------

@router.get("/payment-info", response_model=CommissionPaymentInfoOut)
@limiter.limit("30/minute")
async def commission_payment_info(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # ✅ Reads stay open when soft-locked
):
    """✅ Everything the /commission/pay page needs: what's owed + your Paybill triple."""
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant context for this account.",
        )
    target = current_user.tenant_id

    # Total currently owed (all unpaid events, including today's)
    stmt_owed = select(
        func.count(CommissionEvent.id),
        func.coalesce(func.sum(CommissionEvent.amount), 0),
    ).where(
        CommissionEvent.tenant_id == target,
        CommissionEvent.status == CommissionStatus.unpaid,
    )
    owed_count, owed_total = (await db.execute(stmt_owed)).one()

    # Platform payment details (singleton row)
    settings = await _get_settings(db)

    # Latest submission awaiting verification (if any)
    pending = (
        await db.execute(
            select(CommissionPayment)
            .where(
                CommissionPayment.tenant_id == target,
                CommissionPayment.status == CommissionPaymentStatus.pending,
            )
            .order_by(CommissionPayment.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    # ✅ M-PESA PAYBILL TRIPLE — exactly as entered/confirmed on the phone
    return CommissionPaymentInfoOut(
        outstanding_balance=Decimal(owed_total),
        outstanding_count=int(owed_count),
        paybill_number=settings.platform_paybill if settings else None,
        account_number=settings.platform_account_number if settings else None,
        account_name=settings.platform_account_name if settings else None,
        platform_phone=settings.platform_phone if settings else None,
        platform_email=settings.platform_email if settings else None,
        pending_payment=pending,
    )


@router.post("/payments", response_model=CommissionPaymentOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def submit_commission_payment(
    request: Request,
    payload: CommissionPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ Tenant self-reports a commission payment (M-Pesa code) → awaits your verification."""
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant context for this account.",
        )

    # ✅ One pending submission at a time (no spam / duplicate verification work)
    existing = (
        await db.execute(
            select(CommissionPayment).where(
                CommissionPayment.tenant_id == current_user.tenant_id,
                CommissionPayment.status == CommissionPaymentStatus.pending,
            )
        )
    ).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a payment awaiting verification.",
        )

    payment = CommissionPayment(
        tenant_id=current_user.tenant_id,
        amount=payload.amount,
        reference=payload.reference.strip().upper(),
        notes=payload.notes,
        submitted_by=current_user.id,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


@router.get("/payments", response_model=list[CommissionPaymentOut])
@limiter.limit("30/minute")
async def list_commission_payments(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ Tenant's commission payment history."""
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant context for this account.",
        )

    stmt = (
        select(CommissionPayment)
        .where(CommissionPayment.tenant_id == current_user.tenant_id)
        .order_by(CommissionPayment.created_at.desc())
        .limit(limit)
    )
    payments = (await db.execute(stmt)).scalars().all()
    return payments


# ---------------------------------------------------------------------------
# SUPER ADMIN VERIFICATION QUEUE
# ---------------------------------------------------------------------------

def _require_super_admin(current_user: User) -> None:
    if current_user.role != UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required.",
        )


@router.get("/admin/payments", response_model=list[CommissionPaymentOut])
@limiter.limit("60/minute")
async def list_all_commission_payments(
    request: Request,
    status_filter: Optional[CommissionPaymentStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ Your verification queue. Use ?status=pending for the action list."""
    _require_super_admin(current_user)

    stmt = select(CommissionPayment)
    if status_filter is not None:
        stmt = stmt.where(CommissionPayment.status == status_filter)
    stmt = stmt.order_by(CommissionPayment.created_at.desc()).limit(limit)
    payments = (await db.execute(stmt)).scalars().all()
    return payments


@router.post("/admin/payments/{payment_id}/verify", response_model=CommissionPaymentVerifyResult)
@limiter.limit("30/minute")
async def verify_commission_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ✅ Confirm you received the money. The payment is applied to the tenant's
    unpaid commission events (oldest first). The tenant's soft-lock lifts
    AUTOMATICALLY because /summary recomputes from unpaid events — no extra
    unlock code needed.
    """
    _require_super_admin(current_user)

    payment = await db.get(CommissionPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status != CommissionPaymentStatus.pending:
        raise HTTPException(
            status_code=409, detail=f"Payment is already {payment.status.value}."
        )

    now = datetime.now(timezone.utc)

    # Apply to unpaid events, oldest first
    stmt = (
        select(CommissionEvent)
        .where(
            CommissionEvent.tenant_id == payment.tenant_id,
            CommissionEvent.status == CommissionStatus.unpaid,
        )
        .order_by(CommissionEvent.trip_started_at.asc(), CommissionEvent.id.asc())
    )
    events = (await db.execute(stmt)).scalars().all()

    remaining = Decimal(payment.amount)
    marked = 0
    for event in events:
        if remaining < Decimal(event.amount):
            break  # amounts are uniform; nothing further can be covered
        event.status = CommissionStatus.paid
        event.paid_at = now
        event.payment_reference = payment.reference
        remaining -= Decimal(event.amount)
        marked += 1

    payment.status = CommissionPaymentStatus.verified
    payment.verified_by = current_user.id
    payment.verified_at = now

    await db.commit()
    await db.refresh(payment)

    return CommissionPaymentVerifyResult(
        payment=CommissionPaymentOut.model_validate(payment),
        events_marked_paid=marked,
        unapplied_amount=remaining,
    )


@router.post("/admin/payments/{payment_id}/reject", response_model=CommissionPaymentOut)
@limiter.limit("30/minute")
async def reject_commission_payment(
    request: Request,
    payment_id: int,
    payload: CommissionPaymentRejectIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ Code didn't match your statement. Tenant keeps owing and sees your note."""
    _require_super_admin(current_user)

    payment = await db.get(CommissionPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status != CommissionPaymentStatus.pending:
        raise HTTPException(
            status_code=409, detail=f"Payment is already {payment.status.value}."
        )

    now = datetime.now(timezone.utc)
    payment.status = CommissionPaymentStatus.rejected
    payment.verified_by = current_user.id
    payment.verified_at = now
    payment.notes = payload.notes

    await db.commit()
    await db.refresh(payment)
    return payment


# ---------------------------------------------------------------------------
# PLATFORM SETTINGS (super admin form)
# ---------------------------------------------------------------------------

@router.get("/admin/settings", response_model=PlatformSettingsOut)
@limiter.limit("60/minute")
async def get_platform_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ Loads the Commission Settings form (super admin only)."""
    _require_super_admin(current_user)

    settings = await _get_settings(db)
    if settings is None:
        # Self-heal: the seed guarantees this row, but never 500 if it's missing
        settings = PlatformSettings(
            id=1, commission_amount=Decimal("150.00"), grace_period_days=3
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.put("/admin/settings", response_model=PlatformSettingsOut)
@limiter.limit("10/minute")
async def update_platform_settings(
    request: Request,
    payload: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ✅ Saves the Commission Settings form. Takes effect IMMEDIATELY for all
    tenants: new commission amount on next trip, new Paybill on the pay page,
    new grace period on the next /summary read.
    """
    _require_super_admin(current_user)

    settings = await _get_settings(db)
    if settings is None:
        settings = PlatformSettings(id=1)
        db.add(settings)

    # ✅ Full-state PUT: the form always sends everything, no drift
    for field, value in payload.model_dump().items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)
    return settings

@router.post("/admin/run-daily-job", response_model=dict)
@limiter.limit("5/minute")
async def manual_trigger_daily_commission(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ✅ Manual trigger for testing — runs the routine NOW instead of waiting for 00:05H.
    Super admin only. Use this to verify emails are sending correctly.
    """
    _require_super_admin(current_user)

    from app.jobs.daily_commission import run_daily_commission_routine
    stats = await run_daily_commission_routine(db)
    await db.commit()

    return {
        "message": "Daily commission routine executed successfully",
        "stats": stats,
    }
