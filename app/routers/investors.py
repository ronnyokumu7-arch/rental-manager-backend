import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.core.config import get_settings
from app.dependencies.auth import get_current_user
from app.models.users import User, UserRole
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle
from app.schemas.user import UserOut, UserUpdate
from app.services.email import send_investor_invite_email
from app.services.cache import invalidate_user_cache

router = APIRouter(prefix="/investors", tags=["Investors"])

settings = get_settings()

# Schema for the invite request
class InvestorInviteCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = None


# ---------------------------------------------------------------------------
# 1. CREATE (INVITE) - Mirrors create_user_invite in users.py
# ---------------------------------------------------------------------------
@router.post("/invite", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def invite_investor(
    request: Request,
    payload: InvestorInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Invite a new investor. 
    PATTERN: Uses current_user.tenant_id directly (proven working pattern).
    """
    # 1. Security: Block Super Admins from tenant invites (matches users.py)
    if current_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Super admins cannot generate tenant invite links.",
        )

    # 2. Security: Ensure inviter is an admin
    if current_user.role != UserRole.tenant_admin:
        raise HTTPException(status_code=403, detail="Only Tenant Admins can invite investors.")

    # 3. ✅ CRITICAL: Get tenant_id directly from user (The Proven Pattern)
    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Inviting user does not belong to a tenant.")

    # 4. Check existing user
    stmt = select(User).where(User.email == payload.email.lower())
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(status_code=400, detail="User with this email already exists.")

    # 5. Create User
    invite_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48) # Matches users.py (48h)

    new_investor = User(
        full_name=payload.full_name,
        email=f"invite-{uuid.uuid4().hex}@pending.setup", # Placeholder email (matches users.py)
        phone_number=payload.phone_number,
        role=UserRole.investor,
        tenant_id=tenant_id, # ✅ SECURE: Uses direct tenant_id
        password_hash=None,
        invite_token=invite_token,
        invite_expires_at=expires_at,
        is_onboarded=False,
        email_verified=False,
    )
    db.add(new_investor)
    
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create invite")
        
    await db.refresh(new_investor)
    await invalidate_user_cache(tenant_id)

    # 6. Email Logic
    agency_name = "Rental Garage"
    tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    if tenant: agency_name = tenant.name

    invite_link = f"{settings.frontend_url}/accept-invite?token={invite_token}"
    
    try:
        await send_investor_invite_email(
            to=payload.email, # Send to the real email, not the placeholder
            full_name=payload.full_name,
            invite_link=invite_link,
            agency_name=agency_name,
            expires_at=expires_at.strftime("%B %d, %Y")
        )
    except Exception as e:
        print(f"️ Email failed: {e}")

    if tenant_id:
        await invalidate_user_cache(tenant_id)

    return {
        "message": "Invite created.",
        "invite_token": invite_token,
        "invite_link": invite_link
    }


# ---------------------------------------------------------------------------
# 2. READ (LIST) - Mirrors list_users in users.py
# ---------------------------------------------------------------------------
@router.get("/", response_model=List[UserOut])
@limiter.limit("60/minute")
async def list_investors(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List investors for the current tenant."""
    
    # 1. Security
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    # 2. ✅ CRITICAL: Query using current_user.tenant_id (The Proven Pattern)
    stmt = select(User).where(
        User.tenant_id == current_user.tenant_id,
        User.role == UserRole.investor
    ).order_by(desc(User.created_at))
    
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# 3. UPDATE (PATCH) - Mirrors update_user in users.py
# ---------------------------------------------------------------------------
@router.patch("/{investor_id}", response_model=UserOut)
@limiter.limit("30/minute")
async def update_investor(
    request: Request,
    investor_id: int,
    updates: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an investor. Restricted to Tenant Admins."""
    
    # 1. Security
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    # 2. Fetch
    stmt = select(User).where(User.id == investor_id)
    investor = (await db.execute(stmt)).scalars().first()
    if not investor: raise HTTPException(404, "Investor not found")

    # 3. ✅ CRITICAL: Verify Tenant Isolation using current_user.tenant_id
    if investor.tenant_id != current_user.tenant_id:
        raise HTTPException(403, "Access denied: Tenant mismatch")

    if investor.role != UserRole.investor:
        raise HTTPException(400, "Target is not an investor")

    # 4. Safe Update
    update_data = updates.model_dump(exclude_unset=True)
    
    # Prevent privilege escalation
    for field in ["role", "tenant_id", "permissions", "is_suspended", "is_active"]:
        update_data.pop(field, None)

    for field, value in update_data.items():
        setattr(investor, field, value)

    await db.commit()
    await db.refresh(investor)
    
    if investor.tenant_id: 
        await invalidate_user_cache(investor.tenant_id)
        
    return investor


# ---------------------------------------------------------------------------
# 4. DELETE - Mirrors delete_user in users.py
# ---------------------------------------------------------------------------
@router.delete("/{investor_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_investor(
    request: Request,
    investor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an investor."""
    
    # 1. Security
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    # 2. Fetch
    stmt = select(User).where(User.id == investor_id)
    investor = (await db.execute(stmt)).scalars().first()
    if not investor: raise HTTPException(404, "Investor not found")

    # 3. ✅ CRITICAL: Verify Tenant Isolation
    if investor.tenant_id != current_user.tenant_id:
        raise HTTPException(403, "Access denied: Tenant mismatch")

    if investor.role != UserRole.investor:
        raise HTTPException(400, "Target is not an investor")

    # 4. Constraint Check (Vehicles)
    vehicle_stmt = select(Vehicle).where(Vehicle.owner_id == investor.id)
    if (await db.execute(vehicle_stmt)).scalars().first():
        raise HTTPException(400, "Cannot delete investor with associated vehicles.")

    # 5. Delete
    await db.delete(investor)
    await db.commit()
    
    if investor.tenant_id: 
        await invalidate_user_cache(investor.tenant_id)
        
    return None
