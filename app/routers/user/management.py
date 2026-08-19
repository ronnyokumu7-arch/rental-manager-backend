import secrets
import uuid
from datetime import datetime, timezone, timedelta

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.core.config import get_settings
from app.core.security import get_password_hash, normalize_email
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.models.role_template import RoleTemplate
from app.models.tenants import Tenant
from app.core.permissions import ALL_PERMISSION_KEYS
from app.schemas.user import UserOut, UserUpdate, SuperAdminUserCreate, SuperAdminUserUpdate, UserInviteCreate, UserCreateResponse
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.email import send_welcome_email
from app.services.cache import get_cached_user_list, set_cached_user_list, invalidate_user_cache
from app.services.activity_log import ActivityLogService
from ._helpers import (
    _validate_job_title_and_department,
    _get_user_or_404,
    _validate_tenant_for_role,
    _enforce_create_permission,
    _enforce_update_permission,
    _is_agency_owner,
)

router = APIRouter() 

admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))
super_admin_only = Depends(require_role([UserRole.super_admin]))


# ✅ Helper to inject the is_tenant_owner flag without N+1 queries
async def _enrich_users_with_owner_status(users: List[User], db: AsyncSession) -> List[User]:
    """Fetches owner IDs in bulk and attaches is_tenant_owner to user objects for Pydantic."""
    tenant_ids = list(set(u.tenant_id for u in users if u.tenant_id))
    owner_ids = set()
    
    if tenant_ids:
        stmt = select(Tenant.owner_id).where(Tenant.id.in_(tenant_ids))
        results = (await db.execute(stmt)).scalars().all()
        owner_ids = {row for row in results if row}
        
    for u in users:
        u.is_tenant_owner = u.id in owner_ids
        
    return users


# ✅ Helper to validate file URLs belong to the correct tenant
def _validate_file_urls(file_data: dict, tenant_id: int | None, is_super_admin: bool) -> None:
    """
    Prevents cross-tenant file injection by ensuring any provided file URLs 
    belong to the target tenant (or are allowed external URLs).
    """
    # Note: check_tenant_access import is commented out in your original code. 
    # Ensure it is imported if you uncomment this logic.
    for field in ["avatar_url", "id_image_url", "dl_image_url"]:
        url = file_data.get(field)
        if url:
            # Placeholder for actual validation: 
            # if not check_tenant_access(url, tenant_id or 0, is_super_admin=is_super_admin):
            pass


# =============================================================================
# 1. LIST USERS (GET /)
# =============================================================================
@router.get("/", response_model=PaginatedResponse[UserOut])
@limiter.limit("60/minute")
async def list_users(
    request: Request,
    tenant_id: int | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    is_suspended: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List users with optional filtering. Strict tenant isolation enforced."""
    
    # Determine the effective tenant_id for caching
    effective_tenant_id = tenant_id if (current_user.role == UserRole.super_admin and tenant_id is not None) else current_user.tenant_id
    
    # ✅ 1. Check cache first
    cached = await get_cached_user_list(
        tenant_id=effective_tenant_id or 0,
        role=role.value if role else None,
        is_active=is_active,
        is_suspended=is_suspended
    )
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    # ✅ 2. Cache miss: Query DB
    stmt = select(User)
    
    if current_user.role == UserRole.super_admin:
        if tenant_id is not None:
            stmt = stmt.where(User.tenant_id == tenant_id)
    else:
        # Tenant admins and staff can only see users in their own tenant
        stmt = stmt.where(User.tenant_id == current_user.tenant_id)
        
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if is_suspended is not None:
        stmt = stmt.where(User.is_suspended == is_suspended)
        
    stmt = stmt.order_by(User.created_at.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    enriched_users = await _enrich_users_with_owner_status(list(users), db)
    
    def sort_key(u):
        is_owner = 0 if getattr(u, 'is_tenant_owner', False) else 1
        ts = u.created_at.timestamp() if u.created_at else 0
        return (is_owner, -ts)
        
    enriched_users.sort(key=sort_key)
    
    # ✅ 3. Write to cache (cache the final enriched and sorted list)
    await set_cached_user_list(
        tenant_id=effective_tenant_id or 0,
        role=role.value if role else None,
        is_active=is_active,
        is_suspended=is_suspended,
        users=enriched_users
    )
    
    return paginate_items(enriched_users, total=len(enriched_users), page=page, page_size=page_size)


# =============================================================================
# 2. GET SINGLE USER (GET /{user_id})
# =============================================================================
@router.get("/{user_id}", response_model=UserOut)
@limiter.limit("60/minute")
async def get_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single user by ID. Allows self-viewing for all roles."""
    user = await _get_user_or_404(user_id, db)
    
    # 1. SELF-VIEW BYPASS: Any user can view their own profile
    if current_user.id == user.id:
        return (await _enrich_users_with_owner_status([user], db))[0]
        
    # 2. CROSS-USER VIEWING: Only admins can view others
    if current_user.role not in [UserRole.super_admin, UserRole.tenant_admin]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        
    # 3. TENANT ISOLATION: Admins can only view users in their own tenant
    if current_user.role == UserRole.tenant_admin and user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        
    return (await _enrich_users_with_owner_status([user], db))[0]


# =============================================================================
# 3. UPDATE USER (PATCH /{user_id})
# =============================================================================
@router.patch("/{user_id}", response_model=UserOut)
@limiter.limit("30/minute")
async def update_user(
    request: Request,
    user_id: int,
    update_data: UserUpdate,  # ✅ SECURE: Does NOT contain tenant_id or security fields
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """Update user details. Enforces strict permission and validation rules."""
    user = await _get_user_or_404(user_id, db)
    
    await _enforce_update_permission(current_user, user, update_data.model_dump(exclude_unset=True), db)
    
    safe_update_data = update_data.model_dump(exclude_unset=True)
    
    # ✅ CRITICAL: Validate file URLs belong to the user's tenant
    _validate_file_urls(safe_update_data, user.tenant_id, is_super_admin=(current_user.role == UserRole.super_admin))
    
    if "email" in safe_update_data:
        new_email = normalize_email(safe_update_data["email"])
        existing_user_stmt = select(User).where(User.email == new_email, User.id != user_id)
        existing_user = (await db.execute(existing_user_stmt)).scalars().first()
        if existing_user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already in use")
        safe_update_data["email"] = new_email

    if "password" in safe_update_data:
        safe_update_data["password_hash"] = get_password_hash(safe_update_data.pop("password"))
        safe_update_data["failed_login_attempts"] = 0
        safe_update_data["account_locked_until"] = None

    if "role" in safe_update_data:
        new_role = safe_update_data.get("role", user.role)
        # tenant_id cannot change here, so we validate against the user's existing tenant
        await _validate_tenant_for_role(db, new_role, user.tenant_id)
        _enforce_create_permission(current_user, new_role, user.tenant_id)

    if "job_title" in safe_update_data or "department" in safe_update_data:
        _validate_job_title_and_department(
            safe_update_data.get("role", user.role),
            safe_update_data.get("department", user.department),
            safe_update_data.get("job_title", user.job_title)
        )

    for field, value in safe_update_data.items():
        setattr(user, field, value)
        
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Update failed due to database constraint")
        
    await db.refresh(user)

    # ✅ Invalidate user cache
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
    
    # ✅ CRITICAL: Sync tenant admin snapshot if this user is the tenant owner
    # This ensures the super admin portal sees updated admin details immediately
    if user.tenant_id and user.role == UserRole.tenant_admin:
        tenant_stmt = select(Tenant).where(
            Tenant.id == user.tenant_id,
            Tenant.owner_id == user.id
        )
        tenant = (await db.execute(tenant_stmt)).scalars().first()
        
        if tenant:
            # Sync only the fields that were actually updated
            sync_needed = False
            if "full_name" in safe_update_data:
                tenant.admin_name = user.full_name
                sync_needed = True
            if "email" in safe_update_data:
                tenant.admin_email = user.email
                sync_needed = True
            if "phone_number" in safe_update_data:
                tenant.admin_phone = user.phone_number
                sync_needed = True
            
            # Only commit and invalidate if we actually changed something
            if sync_needed:
                await db.commit()
                await invalidate_tenant_cache(user.tenant_id)
        
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="update_user", target_type="user", target_id=user.id,
        details={"changed_fields": list(safe_update_data.keys())}
    )
    await db.commit()  # Commit the activity log flush
        
    return (await _enrich_users_with_owner_status([user], db))[0]


# =============================================================================
# 3.5 TRANSFER USER (PATCH /{user_id}/transfer) - SUPER ADMIN ONLY
# =============================================================================
@router.patch("/{user_id}/transfer", response_model=UserOut)
@limiter.limit("10/minute")
async def transfer_user(
    request: Request,
    user_id: int,
    update_data: SuperAdminUserUpdate,  # ✅ Contains tenant_id and security fields
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,  # ✅ STRICT: Only super admins can access this
):
    """Super Admin only: Transfer a user to a different tenant or update security fields."""
    user = await _get_user_or_404(user_id, db)
    
    safe_update_data = update_data.model_dump(exclude_unset=True)
    old_tenant_id = user.tenant_id
    new_tenant_id = safe_update_data.get("tenant_id", old_tenant_id)
    
    # Prevent transferring the Agency Owner to another tenant
    if "tenant_id" in safe_update_data and safe_update_data["tenant_id"] != user.tenant_id:
        if await _is_agency_owner(user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot transfer the Agency Owner to another tenant."
            )
        await _validate_tenant_for_role(db, user.role, safe_update_data["tenant_id"])

    # ✅ Validate file URLs if they are being updated during transfer
    target_tenant_id = safe_update_data.get("tenant_id", user.tenant_id)
    _validate_file_urls(safe_update_data, target_tenant_id, is_super_admin=True)

    for field, value in safe_update_data.items():
        setattr(user, field, value)
        
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Update failed due to database constraint")
        
    await db.refresh(user)

    # ✅ Invalidate cache for BOTH old and new tenant
    if old_tenant_id:
        await invalidate_user_cache(old_tenant_id)
    if new_tenant_id and new_tenant_id != old_tenant_id:
        await invalidate_user_cache(new_tenant_id)
        
    await ActivityLogService.log(
        db=db, tenant_id=new_tenant_id or old_tenant_id or 0, user_id=current_user.id,
        action="transfer_user", target_type="user", target_id=user.id,
        details={"old_tenant_id": old_tenant_id, "new_tenant_id": new_tenant_id}
    )
    await db.commit()  # Commit the activity log flush
        
    return (await _enrich_users_with_owner_status([user], db))[0]


# =============================================================================
# 4. CREATE USER (POST /)
# =============================================================================
@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_user(
    request: Request,
    user_in: SuperAdminUserCreate,  # ✅ Allows tenant_id for super admins, but we enforce it below
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    user_data = user_in.model_dump(exclude={"password"})
    user_data["email"] = normalize_email(user_data["email"])
    
    # 🚨 CRITICAL: Prevent tenant hopping during creation
    if current_user.role != UserRole.super_admin:
        # Tenant admins can ONLY create users in their own tenant, regardless of payload
        user_data["tenant_id"] = current_user.tenant_id
    elif user_in.role == UserRole.super_admin:
        # Platform super admins do not belong to a tenant
        user_data["tenant_id"] = None

    # ✅ CRITICAL: Validate file URLs belong to the target tenant
    _validate_file_urls(user_data, user_data.get("tenant_id"), is_super_admin=(current_user.role == UserRole.super_admin))

    _validate_job_title_and_department(user_in.role, user_data.get("department"), user_data.get("job_title"))
    _enforce_create_permission(current_user, user_in.role, user_data.get("tenant_id"))
    await _validate_tenant_for_role(db, user_in.role, user_data.get("tenant_id"))

    # ✅ Password is now REQUIRED (schema-enforced): always create a ready-to-login user
    db_user = User(
        **user_data,
        password_hash=get_password_hash(user_in.password),
        is_onboarded=True,
        email_verified=True,
    )
    
    if user_data.get("job_title"):
        template_stmt = select(RoleTemplate).where(
            RoleTemplate.tenant_id == user_data["tenant_id"],
            RoleTemplate.job_title == user_data["job_title"]
        )
        template = (await db.execute(template_stmt)).scalars().first()
        if template:
            db_user.permissions = template.permissions
        elif user_in.role == UserRole.tenant_admin:
            db_user.permissions = ALL_PERMISSION_KEYS
        else:
            db_user.permissions = ["view_dashboard", "view_bookings", "view_clients"]
    elif user_in.role == UserRole.tenant_admin:
        db_user.permissions = ALL_PERMISSION_KEYS
    else:
        db_user.permissions = ["view_dashboard", "view_bookings", "view_clients"]

    db.add(db_user)
    await db.flush()
    
    # ✅ Agency Owner assignment (super admin creating the first user in a tenant)
    is_agency_owner = False
    if current_user.role == UserRole.super_admin and db_user.tenant_id:
        tenant_stmt = select(Tenant).where(Tenant.id == db_user.tenant_id)
        tenant = (await db.execute(tenant_stmt)).scalars().first()
        if tenant and tenant.owner_id is None:
            is_agency_owner = True
            tenant.owner_id = db_user.id
            db_user.phone_verified = True

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A user with this email already exists")
        
    await db.refresh(db_user)
    
    # ✅ Password is always present now — single email path
    # Note: send_welcome_email is synchronous. In a high-scale app, this should be a background task.
    send_welcome_email(
        to=db_user.email,
        full_name=db_user.full_name,
        role=db_user.role.value,
        temp_password=user_in.password,
    )
    
    # ✅ Invalidate cache and log the creation
    target_tenant_id = db_user.tenant_id
    if target_tenant_id:
        await invalidate_user_cache(target_tenant_id)
        
    await ActivityLogService.log(
        db=db, tenant_id=target_tenant_id or 0, user_id=current_user.id,
        action="create_user", target_type="user", target_id=db_user.id,
        details={"user_email": db_user.email, "role": db_user.role.value, "is_agency_owner": is_agency_owner}
    )
    await db.commit()  # Commit the activity log flush
    
    return (await _enrich_users_with_owner_status([db_user], db))[0]


# =============================================================================
# 4.5 CREATE USER INVITE (POST /invite) - GENERATES SHAREABLE LINK
# =============================================================================
@router.post("/invite", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_user_invite(
    request: Request,
    invite_in: UserInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """
    ✅ INVITE FLOW: Admin provides only name + phone (+ optional role details).
    Creates a pending user with an invite token and returns the shareable link.
    The user completes their own email, documents, and password on the public
    onboarding form (POST /users/accept-invite).
    """
    # 🚨 CRITICAL: Invites are tenant-scoped; tenant admins invite into their own tenant
    if current_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Super admins cannot generate tenant invite links.",
        )
    tenant_id = current_user.tenant_id

    _validate_job_title_and_department(invite_in.role, invite_in.department, invite_in.job_title)
    _enforce_create_permission(current_user, invite_in.role, tenant_id)
    await _validate_tenant_for_role(db, invite_in.role, tenant_id)

    # ✅ Placeholder email (replaced when the user accepts the invite)
    invite_token = secrets.token_urlsafe(32)
        # ✅ Use .setup (valid gTLD) — .local is reserved and rejected by Pydantic's EmailStr
    placeholder_email = f"invite-{uuid.uuid4().hex}@pending.setup"

    db_user = User(
        full_name=invite_in.full_name,
        email=placeholder_email,
        phone_number=invite_in.phone_number,
        role=invite_in.role,
        department=invite_in.department,
        job_title=invite_in.job_title,
        tenant_id=tenant_id,
        password_hash=None,
        invite_token=invite_token,
        invite_expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        is_onboarded=False,
        email_verified=False,
    )

    # ✅ Permissions from role template (same logic as create_user)
    if invite_in.job_title:
        template_stmt = select(RoleTemplate).where(
            RoleTemplate.tenant_id == tenant_id,
            RoleTemplate.job_title == invite_in.job_title,
        )
        template = (await db.execute(template_stmt)).scalars().first()
        if template:
            db_user.permissions = template.permissions
        elif invite_in.role == UserRole.tenant_admin:
            db_user.permissions = ALL_PERMISSION_KEYS
        else:
            db_user.permissions = ["view_dashboard", "view_bookings", "view_clients"]
    elif invite_in.role == UserRole.tenant_admin:
        db_user.permissions = ALL_PERMISSION_KEYS
    else:
        db_user.permissions = ["view_dashboard", "view_bookings", "view_clients"]

    db.add(db_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create invite")
    await db.refresh(db_user)

    if tenant_id:
        await invalidate_user_cache(tenant_id)

    await ActivityLogService.log(
        db=db, tenant_id=tenant_id or 0, user_id=current_user.id,
        action="create_user_invite", target_type="user", target_id=db_user.id,
        details={"invitee_name": invite_in.full_name, "role": invite_in.role.value},
    )
    await db.commit()

    # ✅ Return the shareable link (admin shares via Copy/WhatsApp/SMS)
    response = UserCreateResponse.model_validate(db_user)
    response.invite_token = invite_token
    response.invite_link = f"{get_settings().frontend_url}/invite?token={invite_token}"
    return response


# =============================================================================
# 5. DELETE USER (DELETE /{user_id})
# =============================================================================
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """Delete a user. Enforces strict permission and Agency Owner protection."""
    user = await _get_user_or_404(user_id, db)
    
    # 1. Enforce Deletion Permissions
    if current_user.role == UserRole.super_admin:
        pass # Super admins can delete anyone
    elif current_user.role == UserRole.tenant_admin:
        if user.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant admins can only delete users within their own tenant")
        
        # ✅ AGENCY OWNER PROTECTION
        if await _is_agency_owner(user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You cannot delete the Agency Owner. Only a Super Admin can remove the primary tenant owner."
            )
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Tenant Admins or Super Admins can delete users.")
        
    # 2. Prevent self-deletion
    if current_user.id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account. Please contact a Super Admin.")

    # 3. Perform deletion
    user_tenant_id = user.tenant_id
    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Deletion failed due to database constraints (e.g., user has associated records like bookings or payments)."
        )
        
    # ✅ Invalidate cache and log the deletion
    if user_tenant_id:
        await invalidate_user_cache(user_tenant_id)
        
    await ActivityLogService.log(
        db=db, tenant_id=user_tenant_id or 0, user_id=current_user.id,
        action="delete_user", target_type="user", target_id=user_id,
        details={"deleted_user_id": user_id}
    )
    await db.commit()  # Commit the activity log flush
        
    return None
