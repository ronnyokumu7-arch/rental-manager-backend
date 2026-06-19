from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenant_policies import TenantPolicy
from app.models.users import User, UserRole
from app.schemas.tenant_policy import TenantPolicyCreate, TenantPolicyOut, TenantPolicyUpdate


router = APIRouter(prefix="/policies", tags=["policies"])

# The Bouncer
tenant_admin_only = Depends(require_role([UserRole.tenant_admin, UserRole.super_admin]))


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_authorized_policy(policy_id: int, user: User, db: Session) -> TenantPolicy:
    """Helper to retrieve policy and enforce ownership/access control."""
    policy = db.query(TenantPolicy).filter(
        TenantPolicy.id == policy_id,
        TenantPolicy.tenant_id == user.tenant_id,
    ).first()
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Policy not found"
        )
    return policy


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[TenantPolicyOut])
def list_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(TenantPolicy).filter(
        TenantPolicy.tenant_id == current_user.tenant_id,
    ).order_by(TenantPolicy.display_order).all()


@router.post("/", response_model=TenantPolicyOut, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: TenantPolicyCreate,
    db: Session = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = TenantPolicy(**payload.model_dump(), tenant_id=current_user.tenant_id)
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


@router.patch("/{policy_id}", response_model=TenantPolicyOut)
def update_policy(
    policy_id: int,
    payload: TenantPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = _get_authorized_policy(policy_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    db.commit()
    db.refresh(policy)
    return policy


@router.post("/{policy_id}/toggle", response_model=TenantPolicyOut)
def toggle_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = _get_authorized_policy(policy_id, current_user, db)
    policy.is_active = not policy.is_active
    db.commit()
    db.refresh(policy)
    return policy


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = _get_authorized_policy(policy_id, current_user, db)
    db.delete(policy)
    db.commit()