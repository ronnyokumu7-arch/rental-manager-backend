from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenant_profile import TenantProfile
from app.models.users import User, UserRole
from app.schemas.tenant_profile import TenantProfileCreate, TenantProfileOut, TenantProfileUpdate


router = APIRouter(prefix="/tenant-profile", tags=["tenant-profile"])

# The Bouncer
tenant_admin_only = Depends(require_role([UserRole.tenant_admin, UserRole.super_admin]))


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_authorized_tenant_profile(user: User, db: Session) -> TenantProfile:
    """Helper to retrieve the tenant's profile and enforce access control."""
    profile = db.query(TenantProfile).filter(
        TenantProfile.tenant_id == user.tenant_id
    ).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Profile not set up yet"
        )
    return profile


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=TenantProfileOut)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_authorized_tenant_profile(current_user, db)


@router.post("/", response_model=TenantProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: TenantProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    # Check if profile already exists
    existing = db.query(TenantProfile).filter(
        TenantProfile.tenant_id == current_user.tenant_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile already exists. Use PATCH to update.",
        )
    
    contract_prefix = f"T{current_user.tenant_id}"
    profile = TenantProfile(
        **payload.model_dump(),
        tenant_id=current_user.tenant_id,
        contract_prefix=contract_prefix,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.patch("/", response_model=TenantProfileOut)
def update_profile(
    payload: TenantProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    profile = _get_authorized_tenant_profile(current_user, db)
    
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
        
    db.commit()
    db.refresh(profile)
    return profile