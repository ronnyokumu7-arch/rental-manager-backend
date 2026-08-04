from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenants import Tenant
from app.models.users import User, UserRole

# ---------------------------------------------------------------------------
# STRICT MATRIX ENFORCEMENT
# ---------------------------------------------------------------------------
VALID_ADMIN_TITLES = {"Director", "Manager", "HR"}

VALID_STAFF_DEPARTMENTS = {
    "Fleet & Operations": {"Fleet Manager", "Dispatcher", "Driver"},
    "Finance": {"Accountant", "Cashier"},
    "Sales & Contracts": {"Sales Agent", "Contracts Officer"},
}

def _validate_job_title_and_department(role: UserRole, department: str | None, job_title: str | None) -> None:
    if role == UserRole.super_admin:
        return

    if role == UserRole.tenant_admin:
        if job_title and job_title not in VALID_ADMIN_TITLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Invalid admin title. Must be one of: {', '.join(VALID_ADMIN_TITLES)}"
            )
    elif role == UserRole.tenant_staff:
        if not department or not job_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Staff members must have both a department and a job title assigned."
            )
        if department not in VALID_STAFF_DEPARTMENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Invalid department. Must be one of: {', '.join(VALID_STAFF_DEPARTMENTS.keys())}"
            )
        if job_title not in VALID_STAFF_DEPARTMENTS[department]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Invalid job title for department '{department}'."
            )

# ---------------------------------------------------------------------------
# Agency Owner Helper
# ---------------------------------------------------------------------------
async def _is_agency_owner(user: User, db: AsyncSession) -> bool:
    """Async check if the user is the primary owner of their tenant."""
    if not user.tenant_id:
        return False
    stmt = select(Tenant).where(Tenant.id == user.tenant_id)
    tenant = (await db.execute(stmt)).scalars().first()
    return tenant is not None and tenant.owner_id == user.id

# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------
async def _get_user_or_404(user_id: int, db: AsyncSession) -> User:
    """Async fetch user or raise 404."""
    stmt = select(User).where(User.id == user_id)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user

async def _validate_tenant_for_role(db: AsyncSession, role: UserRole, tenant_id: int | None) -> None:
    """Async validation that tenant exists for non-super-admin roles."""
    if role == UserRole.super_admin:
        return
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id is required for tenant users")
    
    stmt = select(Tenant.id).where(Tenant.id == tenant_id)
    tenant_exists = (await db.execute(stmt)).scalars().first()
    if not tenant_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

def _enforce_create_permission(current_user: User, new_role: UserRole, new_tenant_id: int | None) -> None:
    """Pure logic check for creation permissions (no DB needed)."""
    if current_user.role == UserRole.super_admin:
        return
    if new_role == UserRole.super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant admins cannot create super admin users")
    if new_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant admins can only create users within their own tenant")

async def _enforce_update_permission(current_user: User, target_user: User, update_data: dict, db: AsyncSession) -> None:
    """Async enforcement of update permissions, including Agency Owner protection."""
    # Super Admins can update anyone, anything
    if current_user.role == UserRole.super_admin:
        return

    # 1. SELF-UPDATE RULES
    if current_user.id == target_user.id:
        if current_user.role == UserRole.tenant_admin:
            # Tenant Admins can update everything about themselves except their tenant_id
            # (Note: tenant_id is already stripped from UserUpdate schema, but this is defense-in-depth)
            if "tenant_id" in update_data:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot change your own tenant ID")
        elif current_user.role == UserRole.tenant_staff:
            # Staff can ONLY update basic personal details, compliance docs, and UI preferences
            allowed_fields = {
                "full_name", "email", "phone_number", "password",
                "avatar_url", "id_number", "id_image_url", 
                "dl_number", "dl_image_url", "dl_expiry",
                "theme_preference", "density_preference"
            }
            requested_fields = set(update_data.keys())
            disallowed = requested_fields - allowed_fields
            if disallowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail=f"Staff members can only update their profile, compliance docs, or preferences. Disallowed fields: {', '.join(disallowed)}"
                )
        return

    # 2. CROSS-USER UPDATE RULES (Only Tenant Admins can update others)
    if current_user.role != UserRole.tenant_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Tenant Admins or Super Admins can update other users.")

    if target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant admins can only update users within their own tenant")
    
    if target_user.role == UserRole.super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant admins cannot update super admin users")

    # ✅ AGENCY OWNER PROTECTION
    if await _is_agency_owner(target_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You cannot modify the Agency Owner's profile. Only a Super Admin can do this."
        )

async def _enforce_staff_permission(current_user: User, target_user: User, action: str, db: AsyncSession) -> None:
    """Async enforcement of staff-level actions (verify, suspend, delete), protecting Agency Owners."""
    if current_user.role == UserRole.super_admin:
        return
        
    if target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"Tenant admins can only {action} users within their own tenant"
        )
        
    # ✅ AGENCY OWNER PROTECTION
    # (Self-action is already blocked at the router level, so we just block any admin from acting on the owner)
    if await _is_agency_owner(target_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"Only a Super Admin can {action} the Agency Owner."
        )
        
    if target_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"Tenant admins cannot {action} super admin users"
        )
