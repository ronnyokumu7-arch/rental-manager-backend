# app/routers/payment_verifications.py

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.payments import PaymentVerification, VerificationStatus
from app.services.cache import invalidate_subscription_cache
from app.models.subscriptions import Subscription, PlanType, BillingCycle, SubscriptionStatus
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.payment import (
    PaymentVerificationCreate,
    PaymentVerificationOut,
    PaymentVerificationReview,
)
from app.schemas.pagination import PaginatedResponse, paginate_items

router = APIRouter(prefix="/payment-verifications", tags=["payment-verifications"])

# The Bouncer
super_admin_only = Depends(require_role([UserRole.super_admin]))


@router.post("/", response_model=PaymentVerificationOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")  # 🚨 STRICT: Financial/Subscription state change
async def submit_payment_verification(
    request: Request,
    payload: PaymentVerificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Tenant submits payment proof/reference code (M-Pesa, Bank Transfer, etc.) for admin verification.
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User context is missing a tenant ID.",
        )

    # Check for duplicate reference code
    dup_stmt = select(PaymentVerification).where(
        PaymentVerification.reference_code == payload.reference_code.strip()
    )
    existing = (await db.execute(dup_stmt)).scalars().first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A payment verification request with this reference code already exists.",
        )

    verification = PaymentVerification(
        tenant_id=current_user.tenant_id,
        target_plan=payload.target_plan,
        target_billing_cycle=payload.target_billing_cycle,
        payment_method=payload.payment_method,
        reference_code=payload.reference_code.strip(),
        notes=payload.notes,
        status=VerificationStatus.pending,
    )
    db.add(verification)

    # ✅ NEW: Update the tenant's Subscription status to 'pending_verification'
    now = datetime.now(timezone.utc)
    
    sub_stmt = select(Subscription).where(
        Subscription.tenant_id == current_user.tenant_id
    ).order_by(Subscription.created_at.desc())
    current_sub = (await db.execute(sub_stmt)).scalars().first()

    if current_sub:
        # Update existing subscription to pending
        current_sub.status = SubscriptionStatus.pending_verification
        current_sub.updated_at = now
    else:
        # Fallback: Create a pending subscription if none exists
        try:
            plan_enum = PlanType(payload.target_plan)
        except ValueError:
            plan_enum = PlanType.starter
            
        try:
            cycle_enum = BillingCycle(payload.target_billing_cycle)
        except ValueError:
            cycle_enum = BillingCycle.monthly

        new_sub = Subscription(
            tenant_id=current_user.tenant_id,
            plan=plan_enum,
            billing_cycle=cycle_enum,
            status=SubscriptionStatus.pending_verification,
            starts_at=now,
            auto_renew=True,
            created_at=now,
            updated_at=now,
        )
        db.add(new_sub)

    await db.commit()
    await db.refresh(verification)
    return verification


@router.get("/", response_model=PaginatedResponse[PaymentVerificationOut])
@limiter.limit("30/minute")
async def list_payment_verifications(
    request: Request,
    status_filter: Optional[VerificationStatus] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch verifications. Superadmins see all; regular tenant users see only their own tenant's requests.
    """
    is_superadmin = current_user.role == UserRole.super_admin

    stmt = select(PaymentVerification)

    if not is_superadmin:
        stmt = stmt.where(PaymentVerification.tenant_id == current_user.tenant_id)

    if status_filter:
        stmt = stmt.where(PaymentVerification.status == status_filter)

    # ✅ selectinload is used instead of joinedload for async SQLAlchemy
    stmt = stmt.options(selectinload(PaymentVerification.tenant))
    stmt = stmt.order_by(PaymentVerification.created_at.desc())
    
    results = (await db.execute(stmt)).scalars().unique().all()
    
    # ✅ Manually populate tenant_name for each result
    for verification in results:
        verification.tenant_name = verification.tenant.name if verification.tenant else f"Tenant #{verification.tenant_id}"

    return paginate_items(results, total=len(results), page=page, page_size=page_size)


@router.patch("/{verification_id}/review", response_model=PaymentVerificationOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Superadmin action altering subscription state
async def review_payment_verification(
    request: Request,
    verification_id: int,
    payload: PaymentVerificationReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """
    Superadmin Endpoint: Approve or reject a payment verification submission.
    Upon approval, updates both the tenant record and subscription details.
    """
    ver_stmt = select(PaymentVerification).where(PaymentVerification.id == verification_id)
    verification = (await db.execute(ver_stmt)).scalars().first()
    
    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment verification request not found.",
        )

    now = datetime.now(timezone.utc)
    verification.status = payload.status
    verification.reviewed_by_id = current_user.id
    verification.reviewed_at = now

    if payload.status == VerificationStatus.rejected:
        verification.rejection_reason = payload.rejection_reason
    elif payload.status == VerificationStatus.approved:
        # ✅ Compute expiry once so both Tenant and Subscription stay in sync
        duration_days = 365 if verification.target_billing_cycle == "annual" else 30
        ends_at = now + timedelta(days=duration_days)

        # 1. Update Tenant plan, billing cycle AND subscription state
        tenant_stmt = select(Tenant).where(Tenant.id == verification.tenant_id)
        tenant = (await db.execute(tenant_stmt)).scalars().first()
        
        if tenant:
            if hasattr(tenant, "plan"):
                tenant.plan = verification.target_plan
            if hasattr(tenant, "billing_cycle"):
                tenant.billing_cycle = verification.target_billing_cycle
            # ✅ CRITICAL FIX: Sync tenant-level state so the tenant portal
            # unblocks immediately (mirrors superadmin_manual_provision).
            tenant.subscription_status = SubscriptionStatus.active
            tenant.subscription_ends_at = ends_at
            tenant.grace_period_ends_at = ends_at + timedelta(days=7)
            tenant.trial_ends_at = None

        # 2. Activate or update active subscription
        sub_stmt = select(Subscription).where(
            Subscription.tenant_id == verification.tenant_id
        ).order_by(Subscription.created_at.desc())
        sub = (await db.execute(sub_stmt)).scalars().first()

        if sub:
            sub.plan = verification.target_plan
            sub.billing_cycle = verification.target_billing_cycle
            sub.status = SubscriptionStatus.active
            sub.starts_at = now
            sub.ends_at = ends_at
            sub.auto_renew = True
            sub.updated_at = now
        else:
            # Fallback if subscription was somehow deleted
            sub = Subscription(
                tenant_id=verification.tenant_id,
                plan=verification.target_plan,
                billing_cycle=verification.target_billing_cycle,
                status=SubscriptionStatus.active,
                starts_at=now,
                ends_at=ends_at,
                auto_renew=True,
                created_at=now,
                updated_at=now,
            )
            db.add(sub)

    await db.commit()
    await db.refresh(verification)

    # ✅ CRITICAL FIX: Wipe the Redis subscription cache so the tenant portal
    # instantly reflects the new status instead of serving stale data.
    await invalidate_subscription_cache(verification.tenant_id)

    return verification
