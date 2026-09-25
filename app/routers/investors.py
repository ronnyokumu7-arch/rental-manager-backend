import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.users import User, UserRole
from app.models.tenants import Tenant
from app.services.email import send_investor_invite_email

router = APIRouter(prefix="/investors", tags=["Investors"])

# ✅ Schema for the invite request
class InvestorInviteCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = None

@router.post("/invite", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def invite_investor(
    request: Request,
    payload: InvestorInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Invite a new investor to the agency's fleet.
    Only Tenant Admins or Super Admins can perform this action.
    """
    
    # 1. Security Check: Ensure the inviter is an admin
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agency administrators can invite investors."
        )

    # 2. Check if user already exists
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

    # 4. Create placeholder User record
    new_investor = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        phone_number=payload.phone_number,
        role=UserRole.investor,
        tenant_id=current_user.tenant_id, # Link to the inviting agency
        invite_token=invite_token,
        invite_expires_at=expires_at,
        is_onboarded=False,
        is_active=True,
        email_verified=False, # They verify when they accept
    )
    db.add(new_investor)
    await db.commit()
    await db.refresh(new_investor)

    # 5. Fetch tenant name properly (async)
    agency_name = "Rental Garage"  # Default fallback
    if current_user.tenant_id:
        tenant_stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
        tenant_result = await db.execute(tenant_stmt)
        tenant = tenant_result.scalars().first()
        if tenant:
            agency_name = tenant.name

    # 6. Send the Email (Non-blocking / Graceful Failure)
    invite_link = f"{request.app.state.settings.frontend_url}/accept-invite?token={invite_token}"
    
    try:
        await send_investor_invite_email(
            to=new_investor.email,
            full_name=new_investor.full_name,
            invite_link=invite_link,
            agency_name=agency_name,
            expires_at=expires_at.strftime("%B %d, %Y")
        )
    except Exception as e:
        print(f"️ Failed to send investor invite email: {e}")
        # We don't raise an error here. The user is created, admin can resend later.

    return {
        "message": "Investor invite created successfully.",
        "invite_token": invite_token, # Return token so frontend can show a "Copy Link" fallback
        "invite_link": invite_link
    }
