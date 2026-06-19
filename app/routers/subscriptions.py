from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.subscriptions import BillingCycle, PlanType, Subscription, SubscriptionStatus
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.subscription import SubscriptionCreate, SubscriptionOut, SubscriptionUpdate


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# The Bouncers
super_admin_only = Depends(require_role([UserRole.super_admin]))

PLAN_DURATIONS = {
    PlanType.free_trial: 30,
    PlanType.starter_trial: 14,
    PlanType.starter: None,
    PlanType.pro: None,
    PlanType.enterprise: None,
}

GRACE_PERIOD_DAYS = 7


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_authorized_subscription(subscription_id: int, user: User, db: Session) -> Subscription:
    """Helper to retrieve subscription and enforce ownership/access control."""
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
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
    if billing_cycle == BillingCycle.monthly:
        return starts_at + timedelta(days=30)
    if billing_cycle == BillingCycle.annual:
        return starts_at + timedelta(days=365)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
def create_subscription(
    payload: SubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    tenant = db.query(Tenant).filter(Tenant.id == payload.tenant_id).first()
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

    db.commit()
    db.refresh(db_sub)
    return db_sub


@router.get("/", response_model=list[SubscriptionOut])
def list_subscriptions(
    tenant_id: int | None = None,
    status: SubscriptionStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    query = db.query(Subscription)
    if tenant_id is not None:
        query = query.filter(Subscription.tenant_id == tenant_id)
    if status is not None:
        query = query.filter(Subscription.status == status)
    return query.order_by(Subscription.created_at.desc()).all()


@router.get("/my", response_model=list[SubscriptionOut])
def get_my_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        return []
    return db.query(Subscription).filter(
        Subscription.tenant_id == current_user.tenant_id,
    ).order_by(Subscription.created_at.desc()).all()


@router.get("/{subscription_id}", response_model=SubscriptionOut)
def get_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_authorized_subscription(subscription_id, current_user, db)


@router.patch("/{subscription_id}", response_model=SubscriptionOut)
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    sub = _get_authorized_subscription(subscription_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(sub, field, value)
    db.commit()
    db.refresh(sub)
    return sub


@router.post("/{subscription_id}/suspend", response_model=SubscriptionOut)
def suspend_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    sub = _get_authorized_subscription(subscription_id, current_user, db)
    if sub.status == SubscriptionStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already suspended",
        )
    sub.status = SubscriptionStatus.suspended
    tenant = db.query(Tenant).filter(Tenant.id == sub.tenant_id).first()
    if tenant:
        tenant.subscription_status = SubscriptionStatus.suspended
    db.commit()
    db.refresh(sub)
    return sub


@router.post("/{subscription_id}/reactivate", response_model=SubscriptionOut)
def reactivate_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    sub = _get_authorized_subscription(subscription_id, current_user, db)
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

    tenant = db.query(Tenant).filter(Tenant.id == sub.tenant_id).first()
    if tenant:
        tenant.subscription_status = SubscriptionStatus.active
        tenant.subscription_ends_at = new_ends_at
        tenant.grace_period_ends_at = new_grace

    db.commit()
    db.refresh(sub)
    return sub


@router.post("/{subscription_id}/cancel", response_model=SubscriptionOut)
def cancel_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    sub = _get_authorized_subscription(subscription_id, current_user, db)
    if sub.status == SubscriptionStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already cancelled",
        )
    sub.status = SubscriptionStatus.cancelled
    tenant = db.query(Tenant).filter(Tenant.id == sub.tenant_id).first()
    if tenant:
        tenant.subscription_status = SubscriptionStatus.cancelled
    db.commit()
    db.refresh(sub)
    return sub