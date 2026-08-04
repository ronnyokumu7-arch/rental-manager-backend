from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.schemas.user import UserOut
from app.services.cache import invalidate_user_cache
from app.services.activity_log import ActivityLogService
from ._helpers import (
    _get_user_or_404, 
    _enforce_staff_permission,
    _is_agency_owner,
)

router = APIRouter()

admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))


# =============================================================================
# 1. SUSPEND USER (POST /{user_id}/suspend)
# =============================================================================
@router.post("/{user_id}/suspend", response_model=UserOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Locks a user out of the platform
async def suspend_user(
    request: Request,
    user_id: int,
    reason: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """Suspend a user and record the reason."""
    user = await _get_user_or_404(user_id, db)
    
    # 1. Prevent self-suspension (Business Logic Rule)
    if current_user.id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot suspend yourself")
        
    # 2. Agency Owner Protection (Defense in Depth)
    # Note: _enforce_staff_permission also checks this, but failing fast here is cleaner.
    if current_user.role == UserRole.tenant_admin and await _is_agency_owner(user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You cannot suspend the Agency Owner. Only a Super Admin can take this action."
        )
        
    # 3. Enforce tenant isolation and role permissions (Final Safety Net)
    await _enforce_staff_permission(current_user, user, "suspend", db)
    
    # 4. State check
    if user.is_suspended:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already suspended")
        
    # 5. Apply changes
    user.is_suspended = True
    user.suspension_reason = reason
    
    await db.commit()
    await db.refresh(user)

    # ✅ Invalidate cache and log the suspension
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
        
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="suspend_user", target_type="user", target_id=user.id,
        details={"user_email": user.email, "reason": reason or "No reason provided"}
    )
    await db.commit()  # Commit the activity log flush

    return user


# =============================================================================
# 2. REACTIVATE USER (POST /{user_id}/reactivate)
# =============================================================================
@router.post("/{user_id}/reactivate", response_model=UserOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Restores user access
async def reactivate_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """Reactivate a previously suspended user."""
    user = await _get_user_or_404(user_id, db)
    
    # 1. Agency Owner Protection (Defense in Depth)
    # If a Super Admin suspended the owner, only a Super Admin should reactivate them.
    if current_user.role == UserRole.tenant_admin and await _is_agency_owner(user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You cannot reactivate the Agency Owner. Only a Super Admin can take this action."
        )
        
    # 2. Enforce tenant isolation and role permissions (Final Safety Net)
    await _enforce_staff_permission(current_user, user, "reactivate", db)
    
    # 3. State check
    if not user.is_suspended:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not suspended")
        
    # 4. Apply changes
    user.is_suspended = False
    user.suspension_reason = None
    
    await db.commit()
    await db.refresh(user)

    # ✅ Invalidate cache and log the reactivation
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
        
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="reactivate_user", target_type="user", target_id=user.id,
        details={"user_email": user.email}
    )
    await db.commit()  # Commit the activity log flush

    return user

