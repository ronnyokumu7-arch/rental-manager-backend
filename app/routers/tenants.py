from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import SubscriptionStatus, Tenant
from app.models.users import User, UserRole
from app.schemas.tenant import TenantCreate, TenantOut, TenantUpdate
from app.models.tenant_policies import TenantPolicy, DEFAULT_POLICIES

router = APIRouter(prefix="/tenants", tags=["tenants"])

# The Bouncer
super_admin_only = Depends(require_role([UserRole.super_admin]))

# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------
def _get_authorized_tenant(tenant_id: int, db: Session) -> Tenant:
    """Helper to retrieve a tenant. Since this is super-admin only, we don't need ownership checks."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return tenant

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant: TenantCreate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    db_tenant = Tenant(**tenant.model_dump())
    db.add(db_tenant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant with this email already exists",
        )
    db.refresh(db_tenant)

    # Initialize default policies for the new tenant
    for policy_data in DEFAULT_POLICIES:
        policy = TenantPolicy(
            tenant_id=db_tenant.id,
            section=policy_data["section"],
            title=policy_data["title"],
            content=policy_data["content"],
            display_order=policy_data["display_order"],
            is_active=True,
        )
        db.add(policy)
    db.commit()
    return db_tenant

@router.get("/", response_model=list[TenantOut])
def list_tenants(
    is_active: bool | None = None,
    subscription_status: SubscriptionStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    query = db.query(Tenant)
    if is_active is not None:
        query = query.filter(Tenant.is_active == is_active)
    if subscription_status is not None:
        query = query.filter(Tenant.subscription_status == subscription_status)
    return query.order_by(Tenant.created_at.desc()).all()

@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    return _get_authorized_tenant(tenant_id, db)

@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: int,
    tenant_update: TenantUpdate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    tenant = _get_authorized_tenant(tenant_id, db)
    update_data = tenant_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant with this email already exists",
        )
    db.refresh(tenant)
    return tenant

@router.post("/{tenant_id}/suspend", response_model=TenantOut)
def suspend_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    tenant = _get_authorized_tenant(tenant_id, db)
    if tenant.subscription_status == SubscriptionStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant is already suspended",
        )
    if tenant.subscription_status == SubscriptionStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cancelled tenants cannot be suspended. Reactivate first.",
        )
    tenant.subscription_status = SubscriptionStatus.suspended
    db.commit()
    db.refresh(tenant)
    return tenant

@router.post("/{tenant_id}/reactivate", response_model=TenantOut)
def reactivate_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    tenant = _get_authorized_tenant(tenant_id, db)
    if tenant.subscription_status == SubscriptionStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant is already active",
        )
    tenant.subscription_status = SubscriptionStatus.active
    tenant.grace_period_ends_at = None
    db.commit()
    db.refresh(tenant)
    return tenant

@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    tenant = _get_authorized_tenant(tenant_id, db)
    db.delete(tenant)
    db.commit()
