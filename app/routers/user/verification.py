import secrets
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.config import get_settings
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.schemas.user import UserOut
from app.services.email import send_verification_email
from app.services.cache import invalidate_user_cache
from app.services.activity_log import ActivityLogService
from ._helpers import _get_user_or_404, _enforce_staff_permission

router = APIRouter()

settings = get_settings()
admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))

# ---------------------------------------------------------------------------
# Payload Schemas
# ---------------------------------------------------------------------------
class VerificationPayload(BaseModel):
    channel: Literal["email", "phone"]

class VerifyTokenPayload(BaseModel):
    token: str
    channel: Literal["email", "phone"]

# ---------------------------------------------------------------------------
# 1. SEND VERIFICATION (Automated Flow)
# ---------------------------------------------------------------------------
@router.post("/{user_id}/send-verification", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")  # 🚨 STRICT: Prevents spamming email/SMS providers
async def send_verification(
    request: Request,
    user_id: int,
    payload: VerificationPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """
    Triggers an automated verification email or generates a shareable message.
    """
    user = await _get_user_or_404(user_id, db)
    
    await _enforce_staff_permission(current_user, user, "verify", db)

    # ✅ SECURITY FIX: Prevent token collision. 
    # The model reuses 'invite_token' for both onboarding and verification.
    if not user.is_onboarded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="User must complete onboarding before verification links can be sent."
        )

    if payload.channel == "email" and user.email_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already verified.")
    if payload.channel == "phone" and user.phone_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone is already verified.")

    if payload.channel == "email" and not user.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no email address on file.")
    if payload.channel == "phone" and not user.phone_number:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no phone number on file.")

    # --- Generate Secure Verification Token ---
    verification_token = secrets.token_urlsafe(32)
    verification_link = f"{settings.frontend_url}/verify?token={verification_token}&channel={payload.channel}"
    
    # Assign to user object (not yet committed to DB)
    user.invite_token = verification_token
    user.invite_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    # --- Service Integration ---
    if payload.channel == "email":
        # ✅ CRITICAL FIX: Attempt to send email BEFORE committing to DB.
        # If the email service fails, we rollback and don't leave a dangling, unusable token in the DB.
        success = send_verification_email(
            to=user.email,
            full_name=user.full_name,
            verification_link=verification_link
        )
        if not success:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="Failed to send email. Please check Resend API key and server logs."
            )
    else:
        # For phone, we just return the link for the admin to share. No external service call.
        pass
        
    # ✅ Commit to DB only after external service calls succeed
    await db.commit()

    # ✅ Invalidate cache and log the verification request
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="send_verification_request", target_type="user", target_id=user.id,
        details={"channel": payload.channel}
    )
    await db.commit()  # Commit the activity log flush

    if payload.channel == "email":
        return {"message": f"Verification email sent successfully to {user.email}."}
    else:
        shareable_message = f"Hello {user.full_name}, please verify your phone number for Rental Garage by clicking this secure link: {verification_link}"
        return {
            "message": "Phone verification link generated successfully.",
            "verification_link": verification_link,
            "shareable_message": shareable_message
        }


# ---------------------------------------------------------------------------
# 2. VERIFY TOKEN (Public Endpoint - No Auth Required)
# ---------------------------------------------------------------------------
@router.post("/verify", response_model=UserOut)
@limiter.limit("20/minute")  # 🚨 STRICT: Protects public endpoint from brute-forcing tokens
async def verify_token(
    request: Request,
    payload: VerifyTokenPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint called by the user clicking the link in their email or WhatsApp.
    """
    # 1. Find user by token
    stmt = select(User).where(User.invite_token == payload.token)
    user = (await db.execute(stmt)).scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired verification link.")

    # 2. Check expiration
    if user.invite_expires_at and user.invite_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification link has expired. Please request a new one from your administrator.")

    # ✅ SECURITY FIX: Ensure this isn't an onboarding invite token being accidentally consumed
    if not user.is_onboarded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Please complete your account onboarding first."
        )
        
    # ✅ BUSINESS LOGIC: Do not allow verification for inactive/suspended accounts
    if not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive or suspended. Please contact your administrator."
        )

    # 3. Apply verification based on channel
    if payload.channel == "email":
        if user.email_verified:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already verified.")
        user.email_verified = True
    elif payload.channel == "phone":
        if user.phone_verified:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone is already verified.")
        user.phone_verified = True

    # 4. Invalidate the token so it can't be reused
    user.invite_token = None
    user.invite_expires_at = None
    
    await db.commit()
    await db.refresh(user)
    
    # ✅ Invalidate cache and log the successful self-verification
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
    # Note: user_id is set to user.id here because the user is performing this action on their own account
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=user.id,
        action="verify_account", target_type="user", target_id=user.id,
        details={"channel": payload.channel}
    )
    await db.commit()  # Commit the activity log flush
    
    return user


# ---------------------------------------------------------------------------
# 3. MARK VERIFIED (Manual Admin Override - Shield Button)
# ---------------------------------------------------------------------------
@router.post("/{user_id}/mark-verified", response_model=UserOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Manual override action
async def mark_verified(
    request: Request,
    user_id: int,
    payload: VerificationPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """
    Allows an admin to manually mark a user's email or phone as verified.
    """
    user = await _get_user_or_404(user_id, db)
    
    await _enforce_staff_permission(current_user, user, "verify", db)

    if payload.channel == "email":
        user.email_verified = True
    elif payload.channel == "phone":
        user.phone_verified = True
        
    await db.commit()
    await db.refresh(user)
    
    # ✅ Invalidate cache and log the manual verification override
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="mark_user_verified", target_type="user", target_id=user.id,
        details={"channel": payload.channel}
    )
    await db.commit()  # Commit the activity log flush
    
    return user
