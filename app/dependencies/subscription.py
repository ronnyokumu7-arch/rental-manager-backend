from datetime import datetime, timezone
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.tenants import SubscriptionStatus, Tenant
from app.models.users import User, UserRole
from app.services.cache import (
    get_cached_subscription_status,
    set_cached_subscription_status,
    get_cached_subscription_warning,
    set_cached_subscription_warning,
)


async def get_tenant_subscription_status(
    current_user: User, 
    db: AsyncSession = Depends(get_db)
) -> SubscriptionStatus | None:
    if current_user.role == UserRole.super_admin:
        return None
    if not current_user.tenant_id:
        return None
    
    # ✅ CACHED: Check Redis first (5-minute TTL)
    cached_status = await get_cached_subscription_status(current_user.tenant_id)
    if cached_status is not None:
        return SubscriptionStatus(cached_status)
    
    # Cache miss: fetch from DB
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if tenant:
        # ✅ Write to cache
        await set_cached_subscription_status(current_user.tenant_id, tenant.subscription_status.value)
        return tenant.subscription_status
    return None


async def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    ✅ NOT CACHED: This is a security gatekeeper.
    Always fetch fresh data to ensure suspended/cancelled users are blocked immediately.
    """
    if current_user.role == UserRole.super_admin:
        return current_user

    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tenant associated with this account",
        )

    # ✅ ALWAYS FRESH: Explicitly fetch tenant (no caching for security enforcement)
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tenant associated with this account",
        )

    now = datetime.now(timezone.utc)

    if tenant.subscription_status == SubscriptionStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SUBSCRIPTION_SUSPENDED",
                "message": "Your subscription is suspended. You can view your data but cannot make changes. Please contact support or settle your invoice to reactivate.",
            },
        )

    if tenant.subscription_status == SubscriptionStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SUBSCRIPTION_CANCELLED",
                "message": "Your subscription has been cancelled. Please contact support.",
            },
        )

    if tenant.subscription_status == SubscriptionStatus.past_due:
        if tenant.grace_period_ends_at and now > tenant.grace_period_ends_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SUBSCRIPTION_EXPIRED",
                    "message": "Your grace period has ended. Please settle your invoice to continue.",
                },
            )

    return current_user


async def get_subscription_warning(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    if current_user.role == UserRole.super_admin:
        return None

    if not current_user.tenant_id:
        return None
    
    # ✅ CACHED: Check Redis first (5-minute TTL)
    cached_warning = await get_cached_subscription_warning(current_user.tenant_id)
    if cached_warning is not None:
        # Return empty dict as None (we cache "no warning" as {})
        return cached_warning if cached_warning else None
    
    # Cache miss: fetch from DB
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if tenant is None:
        return None

    now = datetime.now(timezone.utc)
    warning = None

    if tenant.subscription_status == SubscriptionStatus.past_due:
        days_left = None
        if tenant.grace_period_ends_at:
            delta = tenant.grace_period_ends_at - now
            days_left = max(0, delta.days)
        warning = {
            "code": "PAST_DUE",
            "message": f"Your subscription is past due. You have {days_left} day(s) remaining in your grace period. Please settle your invoice to avoid suspension.",
        }

    elif tenant.subscription_status in (
        SubscriptionStatus.trial,
        SubscriptionStatus.starter_trial,
    ):
        if tenant.trial_ends_at:
            delta = tenant.trial_ends_at - now
            days_left = max(0, delta.days)
            if days_left <= 7:
                warning = {
                    "code": "TRIAL_ENDING",
                    "message": f"Your trial ends in {days_left} day(s). Please choose a plan to continue uninterrupted.",
                }

    # ✅ Write to cache
    await set_cached_subscription_warning(current_user.tenant_id, warning)
    
    return warning
