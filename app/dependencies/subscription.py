from datetime import datetime, timezone
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.tenants import SubscriptionStatus
from app.models.users import User, UserRole


def get_tenant_subscription_status(current_user: User, db: Session) -> SubscriptionStatus | None:
    if current_user.role == UserRole.super_admin:
        return None
    if current_user.tenant is None:
        return None
    return current_user.tenant.subscription_status


def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if current_user.role == UserRole.super_admin:
        return current_user

    tenant = current_user.tenant
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


def get_subscription_warning(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict | None:
    if current_user.role == UserRole.super_admin:
        return None

    tenant = current_user.tenant
    if tenant is None:
        return None

    now = datetime.now(timezone.utc)

    if tenant.subscription_status == SubscriptionStatus.past_due:
        days_left = None
        if tenant.grace_period_ends_at:
            delta = tenant.grace_period_ends_at - now
            days_left = max(0, delta.days)
        return {
            "code": "PAST_DUE",
            "message": f"Your subscription is past due. You have {days_left} day(s) remaining in your grace period. Please settle your invoice to avoid suspension.",
        }

    if tenant.subscription_status in (
        SubscriptionStatus.trial,
        SubscriptionStatus.starter_trial,
    ):
        if tenant.trial_ends_at:
            delta = tenant.trial_ends_at - now
            days_left = max(0, delta.days)
            if days_left <= 7:
                return {
                    "code": "TRIAL_ENDING",
                    "message": f"Your trial ends in {days_left} day(s). Please choose a plan to continue uninterrupted.",
                }

    return None