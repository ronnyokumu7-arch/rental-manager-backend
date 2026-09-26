import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.core.config import get_settings
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import TenantScope, get_tenant_scope, require_mutation_tenant_scope
from app.models.users import User, UserRole
from app.models.tenants import Tenant
from app.schemas.user import UserOut, UserUpdate
from app.services.email import send_investor_invite_email
from app.models.vehicles import Vehicle # Ensure this is imported at the top


router = APIRouter(prefix="/investors", tags=["Investors"])

# ✅ Get settings at module level
settings = get_settings()

# ✅ Schema for the invite request
class InvestorInviteCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = None

# ---------------------------------------------------------------------------
# CREATE (INVITE)
# ---------------------------------------------------------------------------
@router.post("/invite", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def invite_investor(
    request: Request,
    payload: InvestorInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # ✅ CRITICAL: Sets RLS context and ensures user has mutation rights for this tenant
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    """
    Invite a new investor to the agency's fleet.
    Strictly scoped to the current tenant context.
    """
    
    # 1. Security Check: Ensure the inviter is an admin of THIS tenant
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agency administrators can invite investors."
        )

    # 2. Check if user already exists (Global check is fine here, but we scope the creation)
    stmt = select(User).where(User.email == payload.email.lower())
    existing_user = (await db.execute(stmt)).scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="A user with this email already exists."
        )

    # 3. Generate Invite Token (Valid for 7 days)
    invite_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    # ✅ CRITICAL: Use scope.tenant_id to ensure RLS allows the INSERT
    if not scope.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant context for invitation."
        )

    # 4. Create placeholder User record
    new_investor = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        phone_number=payload.phone_number,
        role=UserRole.investor,
        tenant_id=scope.tenant_id, # ✅ SECURE: Uses scoped tenant ID
        invite_token=invite_token,
        invite_expires_at=expires_at,
        is_onboarded=False,
        is_active=True,
        email_verified=False,
    )
    db.add(new_investor)
    await db.commit()
    await db.refresh(new_investor)

    # 5. Fetch tenant name properly (async)
    agency_name = "Rental Garage"  # Default fallback
    tenant_stmt = select(Tenant).where(Tenant.id == scope.tenant_id)
    tenant_result = await db.execute(tenant_stmt)
    tenant = tenant_result.scalars().first()
    if tenant:
        agency_name = tenant.name

    # 6. Send the Email (Non-blocking / Graceful Failure)
    invite_link = f"{settings.frontend_url}/accept-invite?token={invite_token}"
    
    try:
        await send_investor_invite_email(
            to=new_investor.email,
            full_name=new_investor.full_name,
            invite_link=invite_link,
            agency_name=agency_name,
            expires_at=expires_at.strftime("%B %d, %Y")
        )
    except Exception as e:
        print(f"⚠️ Failed to send investor invite email: {e}")

    return {
        "message": "Investor invite created successfully.",
        "invite_token": invite_token,
        "invite_link": invite_link
    }


# ---------------------------------------------------------------------------
# READ (LIST)
# ---------------------------------------------------------------------------
@router.get("/", response_model=List[UserOut])
@limiter.limit("30/minute")
async def list_investors(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # ✅ CRITICAL: Sets RLS context for reading data
    scope: TenantScope = Depends(get_tenant_scope),
):
    """
    List all investors for the current tenant.
    Scoped strictly to the tenant context provided by the dependency.
    """
    # 1. Security Check
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agency administrators can view investors."
        )

    # 2. Query database using the scoped tenant_id
    # ✅ SECURE: The DB session now has the RLS context set by get_tenant_scope
    stmt = (
        select(User)
        .where(
            User.tenant_id == scope.tenant_id,
            User.role == UserRole.investor
        )
        .order_by(desc(User.created_at))
    )
    
    result = await db.execute(stmt)
    investors = result.scalars().all()
    
    return investors


# ---------------------------------------------------------------------------
# UPDATE INVESTOR (PATCH)
# ---------------------------------------------------------------------------
@router.patch("/{investor_id}", response_model=UserOut)
@limiter.limit("30/minute")
async def update_investor(
    request: Request,
    investor_id: int,
    updates: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    """
    Update an investor's profile. 
    Restricted to Tenant Admins. Prevents privilege escalation.
    """
    # 1. Fetch the target user
    stmt = select(User).where(User.id == investor_id)
    investor = (await db.execute(stmt)).scalars().first()

    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")

    # 2. Security: Verify Tenant Isolation
    if investor.tenant_id != scope.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # 3. Security: Verify Role (Ensure we aren't accidentally updating an Admin)
    if investor.role != UserRole.investor:
        raise HTTPException(status_code=400, detail="Target user is not an investor")

    # 4. Prepare Safe Update Data
    update_data = updates.model_dump(exclude_unset=True)
    
    # 🚨 CRITICAL: Prevent Privilege Escalation
    # Admins cannot change an investor's role or move them to another tenant via this endpoint
    update_data.pop("role", None)
    update_data.pop("tenant_id", None)
    update_data.pop("permissions", None)
    update_data.pop("is_suspended", None) # Use a dedicated suspend endpoint if needed

    # 5. Apply Updates
    for field, value in update_data.items():
        setattr(investor, field, value)

    await db.commit()
    await db.refresh(investor)
    
    # Invalidate cache
    if investor.tenant_id:
        from app.services.cache import invalidate_user_cache
        await invalidate_user_cache(investor.tenant_id)

    return investor


# ---------------------------------------------------------------------------
# DELETE INVESTOR
# ---------------------------------------------------------------------------
@router.delete("/{investor_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_investor(
    request: Request,
    investor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    """
    Remove an investor. 
    Fails if the investor owns vehicles (to prevent orphaned assets).
    """
    # 1. Fetch the target user
    stmt = select(User).where(User.id == investor_id)
    investor = (await db.execute(stmt)).scalars().first()

    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")

    # 2. Security: Verify Tenant Isolation
    if investor.tenant_id != scope.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # 3. Security: Verify Role
    if investor.role != UserRole.investor:
        raise HTTPException(status_code=400, detail="Target user is not an investor")

    # 4. Constraint Check: Do they own vehicles?
    vehicle_stmt = select(Vehicle).where(Vehicle.owner_id == investor.id)
    vehicles = (await db.execute(vehicle_stmt)).scalars().all()
    
    if vehicles:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete investor. They own {len(vehicles)} vehicle(s). Please reassign or delete vehicles first."
        )

    # 5. Perform Deletion
    await db.delete(investor)
    await db.commit()

    # Invalidate cache
    if investor.tenant_id:
        from app.services.cache import invalidate_user_cache
        await invalidate_user_cache(investor.tenant_id)

    return None
