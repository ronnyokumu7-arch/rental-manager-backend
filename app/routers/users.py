from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_password_hash, normalize_email
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.email import send_welcome_email, send_password_changed


router = APIRouter(prefix="/users", tags=["users"])

# The Bouncers
admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


def _validate_tenant_for_role(db: Session, role: UserRole, tenant_id: int | None) -> None:
    """Ensure tenant exists if the role requires it."""
    if role == UserRole.super_admin:
        return
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id is required for tenant users",
        )
    tenant_exists = db.query(Tenant.id).filter(Tenant.id == tenant_id).first()
    if not tenant_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )


def _enforce_create_permission(current_user: User, new_role: UserRole, new_tenant_id: int | None) -> None:
    if current_user.role == UserRole.super_admin:
        return
    if new_role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admins cannot create super admin users",
        )
    if new_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admins can only create users within their own tenant",
        )


def _enforce_update_permission(current_user: User, target_user: User, update_data: dict) -> None:
    if current_user.role == UserRole.super_admin:
        return
    
    # Self-update rules
    if current_user.id == target_user.id:
        forbidden_fields = {"role", "tenant_id", "is_active"}
        if forbidden_fields.intersection(update_data.keys()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot change your own role, tenant, or active status",
            )
        return

    # Tenant admin rules
    if target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admins can only update users within their own tenant",
        )
    if target_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admins cannot update super admin users",
        )


def _enforce_staff_permission(current_user: User, target_user: User, action: str) -> None:
    """Helper for suspend/delete/reactivate actions."""
    if current_user.role == UserRole.super_admin:
        return
    if target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant admins can only {action} users within their own tenant",
        )
    if target_user.role in (UserRole.super_admin, UserRole.tenant_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant admins can only {action} tenant staff",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = admin_or_above,
):
    _enforce_create_permission(current_user, user.role, user.tenant_id)
    _validate_tenant_for_role(db, user.role, user.tenant_id)

    user_data = user.model_dump(exclude={"password"})
    user_data["email"] = normalize_email(user_data["email"])
    if user.role == UserRole.super_admin:
        user_data["tenant_id"] = None

    db_user = User(**user_data, password_hash=get_password_hash(user.password))
    db.add(db_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    db.refresh(db_user)
    send_welcome_email(
        to=db_user.email,
        full_name=db_user.full_name,
        role=db_user.role.value,
        temp_password=user.password,
    )
    return db_user


@router.get("/", response_model=list[UserOut])
def list_users(
    tenant_id: int | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    is_suspended: bool | None = None,
    db: Session = Depends(get_db),
    current_user: User = admin_or_above,
):
    query = db.query(User)

    # Security: Enforce tenant isolation
    if current_user.role == UserRole.super_admin:
        # Super admins can optionally filter by tenant
        if tenant_id:
            query = query.filter(User.tenant_id == tenant_id)
    else:
        # Standard admins are locked into their own tenant
        query = query.filter(User.tenant_id == current_user.tenant_id)

    # Apply optional filters
    if role is not None:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if is_suspended is not None:
        query = query.filter(User.is_suspended == is_suspended)

    return query.order_by(User.created_at.desc()).all()


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_user_or_404(user_id, db)

    # Authorization logic
    if current_user.role == UserRole.super_admin or current_user.id == user_id:
        return user
    if current_user.role == UserRole.tenant_admin and user.tenant_id == current_user.tenant_id:
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to view this user",
    )


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_user_or_404(user_id, db)
    update_data = user_update.model_dump(exclude_unset=True)
    if "email" in update_data and update_data["email"] is not None:
        update_data["email"] = normalize_email(update_data["email"])
    
    _enforce_update_permission(current_user, user, update_data)

    new_role = update_data.get("role", user.role)
    new_tenant_id = update_data.get("tenant_id", user.tenant_id)
    _validate_tenant_for_role(db, new_role, new_tenant_id)

    if new_role == UserRole.super_admin:
        update_data["tenant_id"] = None

    password = update_data.pop("password", None)
    if password is not None:
        user.password_hash = get_password_hash(password)

    for field, value in update_data.items():
        setattr(user, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    db.refresh(user)
    if password is not None:
        send_password_changed(
            to=user.email,
            full_name=user.full_name,
        )
    return user


@router.post("/{user_id}/suspend", response_model=UserOut)
def suspend_user(
    user_id: int,
    reason: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_user_or_404(user_id, db)
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot suspend yourself",
        )
    
    _enforce_staff_permission(current_user, user, "suspend")
    
    if user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already suspended",
        )
    user.is_suspended = True
    user.suspension_reason = reason
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reactivate", response_model=UserOut)
def reactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_user_or_404(user_id, db)
    _enforce_staff_permission(current_user, user, "reactivate")
    
    if not user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not suspended",
        )
    user.is_suspended = False
    user.suspension_reason = None
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_user_or_404(user_id, db)
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    
    _enforce_staff_permission(current_user, user, "delete")
    
    db.delete(user)
    db.commit()
