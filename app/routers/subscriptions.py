from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import Tenant
from app.models.subscriptions import BillingCycle, PlanType, Subscription, SubscriptionStatus
from app.models.users import User, UserRole
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.subscription import SubscriptionCreate, SubscriptionOut, SubscriptionUpdate
from app.services.cache import invalidate_subscription_cache  # ✅ NEW: For cache invalidation

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# The Bouncers
super_admin_only = Depends(require_role([UserRole.super_admin]))

GRACE_PERIOD_DAYS = 7


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

async def _get_authorized_subscription(subscription_id: int, user: User, db: AsyncSession) -> Subscription:
    """Async helper to retrieve subscription and enforce ownership/access control."""
    stmt = select(Subscription).where(Subscription.id == subscription_id)
    result = await db.execute(stmt)
    sub = result.scalars().first()
    
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )
    
    # Super admins see all, regular users only their own
    if user.role != UserRole.super_admin and sub.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own subscriptions",
        )
    return sub


def _compute_ends_at(plan: PlanType, billing_cycle: BillingCycle, starts_at: datetime) -> datetime | None:
    if plan == PlanType.free_trial:
        return starts_at + timedelta(days=30)
    if plan == PlanType.starter_trial:
        return starts_at + timedelta(days=14)
    if plan == PlanType.pay_as_you_go:
        return None  # Indefinite term
    if billing_cycle == BillingCycle.monthly:
        return starts_at + timedelta(days=30)
    if billing_cycle == BillingCycle.annual:
        return starts_at + timedelta(days=365)
    return None


# ---------------------------------------------------------------------------
# Request & Response Schemas (For Manual Provision)
# ---------------------------------------------------------------------------

class ManualProvisionRequest(BaseModel):
    tenant_id: int
    plan: str = Field(..., description="'starter', 'pro', or 'enterprise'")
    billing_cycle: str = Field(..., description="'monthly', 'annual', or 'pay_as_you_go'")
    payment_method: str = Field(..., description="'bank_transfer', 'mpesa_manual', 'cash', 'cheque'")
    reference_code: str = Field(..., description="External transaction or receipt reference code")
    amount_paid: Optional[float] = Field(default=0.0, description="Amount paid for this period")
    notes: Optional[str] = None
    custom_expiry_days: Optional[int] = Field(default=None, description="Override default duration")


# ---------------------------------------------------------------------------
# Routes - Tenant Facing
# ---------------------------------------------------------------------------

@router.get("/my", response_model=PaginatedResponse[SubscriptionOut])
@limiter.limit("60/minute")
async def get_my_subscriptions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user's tenant subscriptions."""
    if current_user.tenant_id is None:
        return paginate_items([], total=0, page=page, page_size=page_size)
    stmt = select(Subscription).where(
        Subscription.tenant_id == current_user.tenant_id,
    ).order_by(Subscription.created_at.desc())
    
    result = await db.execute(stmt)
    subscriptions = result.scalars().all()
    return paginate_items(subscriptions, total=len(subscriptions), page=page, page_size=page_size)


@router.get("/", response_model=PaginatedResponse[SubscriptionOut])
@limiter.limit("60/minute")
async def list_subscriptions(
    request: Request,
    tenant_id: int | None = None,
    status: SubscriptionStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """List all subscriptions (Super Admin only)."""
    stmt = select(Subscription)
    if tenant_id is not None:
        stmt = stmt.where(Subscription.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(Subscription.status == status)
        
    stmt = stmt.order_by(Subscription.created_at.desc())
    result = await db.execute(stmt)
    subscriptions = result.scalars().all()
    return paginate_items(subscriptions, total=len(subscriptions), page=page, page_size=page_size)


@router.post("/", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")  # 🚨 STRICT: Affects tenant access
async def create_subscription(
    request: Request,
    payload: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """Create a new subscription (Super Admin only)."""
    tenant_stmt = select(Tenant).where(Tenant.id == payload.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    now = datetime.now(timezone.utc)
    ends_at = _compute_ends_at(payload.plan, payload.billing_cycle, now)
    grace_period_ends_at = (ends_at + timedelta(days=GRACE_PERIOD_DAYS)) if ends_at else None

    sub_status = (
        SubscriptionStatus.trial if payload.plan == PlanType.free_trial
        else SubscriptionStatus.starter_trial if payload.plan == PlanType.starter_trial
        else SubscriptionStatus.active
    )

    db_sub = Subscription(
        tenant_id=payload.tenant_id,
        plan=payload.plan,
        billing_cycle=payload.billing_cycle,
        status=sub_status,
        starts_at=now,
        ends_at=ends_at,
        grace_period_ends_at=grace_period_ends_at,
        auto_renew=payload.auto_renew,
    )
    db.add(db_sub)

    tenant.plan = payload.plan.value
    tenant.subscription_status = sub_status
    tenant.trial_ends_at = ends_at if payload.plan in (PlanType.free_trial, PlanType.starter_trial) else None
    tenant.subscription_ends_at = ends_at
    tenant.grace_period_ends_at = grace_period_ends_at

    await db.commit()
    await db.refresh(db_sub)
    
    # ✅ CRITICAL: Invalidate cache so warnings update immediately
    await invalidate_subscription_cache(payload.tenant_id)
    return db_sub


@router.get("/{subscription_id}", response_model=SubscriptionOut)
@limiter.limit("60/minute")
async def get_subscription(
    request: Request,
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific subscription by ID."""
    return await _get_authorized_subscription(subscription_id, current_user, db)


@router.patch("/{subscription_id}", response_model=SubscriptionOut)
@limiter.limit("30/minute")
async def update_subscription(
    request: Request,
    subscription_id: int,
    payload: SubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user), 
):
    """Update subscription (e.g., toggle auto_renew)."""
    sub = await _get_authorized_subscription(subscription_id, current_user, db)
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(sub, field, value)
        
    await db.commit()
    await db.refresh(sub)
    
    # ✅ Invalidate cache in case billing-related fields changed
    await invalidate_subscription_cache(sub.tenant_id)
    return sub


@router.post("/{subscription_id}/suspend", response_model=SubscriptionOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Affects tenant access
async def suspend_subscription(
    request: Request,
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """Suspend a subscription (Super Admin only)."""
    sub = await _get_authorized_subscription(subscription_id, current_user, db)
    if sub.status == SubscriptionStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already suspended",
        )
    sub.status = SubscriptionStatus.suspended
    
    tenant_stmt = select(Tenant).where(Tenant.id == sub.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if tenant:
        tenant.subscription_status = SubscriptionStatus.suspended
        
    await db.commit()
    await db.refresh(sub)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_subscription_cache(sub.tenant_id)
    return sub


@router.post("/{subscription_id}/reactivate", response_model=SubscriptionOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Affects tenant access
async def reactivate_subscription(
    request: Request,
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """Reactivate a suspended subscription (Super Admin only)."""
    sub = await _get_authorized_subscription(subscription_id, current_user, db)
    if sub.status == SubscriptionStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already active",
        )
    if sub.status == SubscriptionStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cancelled subscriptions cannot be reactivated. Create a new subscription instead.",
        )

    now = datetime.now(timezone.utc)
    new_ends_at = _compute_ends_at(sub.plan, sub.billing_cycle, now)
    new_grace = (new_ends_at + timedelta(days=GRACE_PERIOD_DAYS)) if new_ends_at else None

    sub.status = SubscriptionStatus.active
    sub.starts_at = now
    sub.ends_at = new_ends_at
    sub.grace_period_ends_at = new_grace

    tenant_stmt = select(Tenant).where(Tenant.id == sub.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if tenant:
        tenant.subscription_status = SubscriptionStatus.active
        tenant.subscription_ends_at = new_ends_at
        tenant.grace_period_ends_at = new_grace

    await db.commit()
    await db.refresh(sub)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_subscription_cache(sub.tenant_id)
    return sub


@router.post("/{subscription_id}/cancel", response_model=SubscriptionOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Affects tenant access
async def cancel_subscription(
    request: Request,
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """Cancel a subscription (Super Admin only)."""
    sub = await _get_authorized_subscription(subscription_id, current_user, db)
    if sub.status == SubscriptionStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already cancelled",
        )
    sub.status = SubscriptionStatus.cancelled
    
    tenant_stmt = select(Tenant).where(Tenant.id == sub.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if tenant:
        tenant.subscription_status = SubscriptionStatus.cancelled
        
    await db.commit()
    await db.refresh(sub)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_subscription_cache(sub.tenant_id)
    return sub


# ---------------------------------------------------------------------------
# Routes - Super Admin Manual Provisioning
# ---------------------------------------------------------------------------

@router.post("/admin/manual-activate", response_model=SubscriptionOut)
@limiter.limit("5/minute")  # 🚨 EXTREMELY STRICT: Manual financial provisioning
async def superadmin_manual_provision(
    request: Request,
    payload: ManualProvisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """
    Super Admin Endpoint: Manually provisions or upgrades a tenant's subscription tier
    after verifying offline/bank payments.
    """
    clean_plan = payload.plan.lower().strip()
    if clean_plan == "professional":
        clean_plan = "pro"

    if clean_plan not in ["starter", "pro", "enterprise", "pay_as_you_go"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid plan. Must be 'starter', 'pro', 'enterprise', or 'pay_as_you_go'."
        )

    clean_cycle = payload.billing_cycle.lower().strip()
    if clean_cycle not in ["monthly", "annual", "pay_as_you_go"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid billing cycle. Must be 'monthly', 'annual', or 'pay_as_you_go'."
        )

    now = datetime.now(timezone.utc)
    if payload.custom_expiry_days and payload.custom_expiry_days > 0:
        duration_days = payload.custom_expiry_days
    else:
        duration_days = 365 if clean_cycle == "annual" else 30

    ends_at = now + timedelta(days=duration_days)

    sub_stmt = select(Subscription).where(
        Subscription.tenant_id == payload.tenant_id
    ).order_by(Subscription.created_at.desc())
    sub = (await db.execute(sub_stmt)).scalars().first()

    if sub:
        sub.plan = clean_plan
        sub.billing_cycle = clean_cycle
        sub.status = SubscriptionStatus.active
        sub.starts_at = now
        sub.ends_at = ends_at
        sub.auto_renew = True
        sub.updated_at = now
    else:
        sub = Subscription(
            tenant_id=payload.tenant_id,
            plan=clean_plan,
            billing_cycle=clean_cycle,
            status=SubscriptionStatus.active,
            starts_at=now,
            ends_at=ends_at,
            auto_renew=True,
            created_at=now,
            updated_at=now,
        )
        db.add(sub)

    # ✅ CRITICAL FIX: Sync tenant-level settings (was missing status/date updates)
    tenant_stmt = select(Tenant).where(Tenant.id == payload.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if tenant:
        tenant.plan = clean_plan
        tenant.billing_cycle = clean_cycle
        tenant.subscription_status = SubscriptionStatus.active  # ✅ Ensure tenant is unblocked
        tenant.subscription_ends_at = ends_at
        tenant.grace_period_ends_at = ends_at + timedelta(days=GRACE_PERIOD_DAYS)
        tenant.trial_ends_at = None  # Clear trial status if manually activated

    await db.commit()
    await db.refresh(sub)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_subscription_cache(payload.tenant_id)
    return sub
