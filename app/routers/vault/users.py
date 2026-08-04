# app/routers/vault/users.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.user import UserOut
from app.services.cache import invalidate_user_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/users", tags=["vault-users"])

@router.get("/", response_model=PaginatedResponse[UserOut])
@limiter.limit("60/minute")
async def list_vault_users(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch users that are either inactive or suspended
    stmt = select(User).where(
        User.tenant_id == current_user.tenant_id,
        or_(
            User.is_active == False,
            User.is_suspended == True
        )
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            User.full_name.ilike(search_lower) |
            User.email.ilike(search_lower)
        )
        
    # Sort by most recently updated (deactivated/suspended) first
    stmt = stmt.order_by(User.updated_at.desc())
    
    result = await db.execute(stmt)
    users = result.scalars().all()
    return paginate_items(users, total=len(users), page=page, page_size=page_size)

@router.post("/{user_id}/restore", response_model=UserOut)
@limiter.limit("10/minute")
async def restore_vault_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(User).where(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found in vault")
        
    # Restore logic: Reactivate and unsuspend
    user.is_active = True
    user.is_suspended = False
    user.suspension_reason = None
    
    await db.commit()
    await db.refresh(user)

    # ✅ Invalidate user cache so the restored user appears in active lists
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
        
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="restore_user", target_type="user", target_id=user.id,
        details={"user_email": user.email}
    )
    await db.commit()  # Commit the activity log flush

    return user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Prevent admins from accidentally deleting themselves
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account from the vault")

    stmt = select(User).where(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found in vault")
        
    # Capture details before permanent deletion (object becomes detached after delete)
    user_email = user.email
    user_tenant_id = user.tenant_id
        
    # Hard delete: Permanent destruction from the database
    # Note: SQLAlchemy will handle cascading deletes based on your model relationships
    await db.delete(user)
    await db.commit()

    # ✅ Invalidate user cache
    if user_tenant_id:
        await invalidate_user_cache(user_tenant_id)
        
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=user_tenant_id or 0, user_id=current_user.id,
        action="hard_delete_user", target_type="user", target_id=user_id,
        details={"user_email": user_email}
    )
    await db.commit()  # Commit the activity log flush
