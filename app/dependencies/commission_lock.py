# app/dependencies/commission_lock.py
"""
✅ SOFT-LOCK GATE

Blocks revenue-generating mutations when the tenant's oldest unpaid
commission event is older than the platform grace period.

Rules:
- Super admins always pass
- Tenants inside their 30-day free trial always pass
- No unpaid events → pass
- Otherwise: 402 Payment Required with a clear message
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies.subscription import require_active_subscription
from app.models.commission import CommissionEvent, CommissionStatus
from app.models.platform_settings import PlatformSettings
from app.models.tenants import Tenant
from app.models.users import User, UserRole

PLATFORM_TZ = ZoneInfo("Africa/Nairobi")
DEFAULT_GRACE_DAYS = 3


async def require_not_commission_locked(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
) -> User:
    """
    ✅ Usage in any mutation endpoint:
        current_user: User = Depends(require_not_commission_locked)
    """
    # Super admins bypass the gate
    if current_user.role == UserRole.super_admin:
        return current_user
    if current_user.tenant_id is None:
        return current_user

    # ✅ Trial exemption: free trips during the 30-day trial
    tenant = await db.get(Tenant, current_user.tenant_id)
    now_utc = datetime.now(timezone.utc)
    if (
        tenant is not None
        and tenant.trial_ends_at is not None
        and tenant.trial_ends_at > now_utc
    ):
        return current_user

    # Oldest unpaid commission event
    oldest_unpaid_at = (
        await db.execute(
            select(func.min(CommissionEvent.trip_started_at)).where(
                CommissionEvent.tenant_id == current_user.tenant_id,
                CommissionEvent.status == CommissionStatus.unpaid,
            )
        )
    ).scalar_one_or_none()

    if oldest_unpaid_at is None:
        return current_user  # nothing owed → not locked

    # Grace period from PlatformSettings (super-admin configurable)
    settings = (
        await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    ).scalars().first()
    grace_days = settings.grace_period_days if settings else DEFAULT_GRACE_DAYS

    now_eat = datetime.now(PLATFORM_TZ)
    age_days = (
        now_eat.date() - oldest_unpaid_at.astimezone(PLATFORM_TZ).date()
    ).days

    if grace_days - age_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Account soft-locked: settle your outstanding commission to resume "
                "operations. Visit Commission → Pay."
            ),
        )

    return current_user
