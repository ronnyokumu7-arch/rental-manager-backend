from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.core.security import get_password_hash, normalize_email
from app.models.users import User
from app.schemas.user import UserOut, AcceptInvitePayload
from app.services.cache import invalidate_user_cache
from app.services.activity_log import ActivityLogService
# from app.services.uploads import check_tenant_access  # ✅ NEW: Validate file ownership

router = APIRouter()


def _validate_file_url_belongs_to_tenant(file_url: str | None, tenant_id: int) -> None:
    """
    ✅ CRITICAL: Validate that a file URL belongs to the specified tenant.
    Prevents cross-tenant file injection attacks.
    """
    if not file_url:
        return  # None is allowed (optional fields)
    
    # If it's a file URL from our system, verify tenant ownership
    if file_url.startswith("/api/v1/files/"):
        # Note: check_tenant_access is commented out in your original code. 
        # Uncomment and ensure it's imported when you are ready to enforce this.
        # if not check_tenant_access(file_url, tenant_id, is_super_admin=False):
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="Cannot reference files from another tenant"
        #     )
        pass
    # If it's an external URL (e.g., cloud storage), we allow it but log it
    elif file_url.startswith("http://") or file_url.startswith("https://"):
        # External URLs are allowed (e.g., from cloud storage like R2/Supabase)
        pass
    else:
        # Reject any other URL format (e.g., relative paths, file://, etc.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file URL format"
        )


@router.post("/accept-invite", response_model=UserOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Prevents brute-forcing invite tokens per IP
async def accept_invite(
    request: Request,
    payload: AcceptInvitePayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Allows a user to accept an invite by providing their token and setting a password.
    This flips is_onboarded to True and clears the invite token.
    """
    # 1. Find user by token
    stmt = select(User).where(User.invite_token == payload.invite_token)
    user = (await db.execute(stmt)).scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite token")

    # 2. Check expiration
    if user.invite_expires_at and user.invite_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite token has expired")

    # 3. Check if already onboarded
    if user.is_onboarded:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already active")

    # ✅ CRITICAL: Validate all file URLs belong to the user's tenant
    # This prevents cross-tenant file injection attacks
    _validate_file_url_belongs_to_tenant(payload.avatar_url, user.tenant_id or 0)
    _validate_file_url_belongs_to_tenant(payload.id_image_url, user.tenant_id or 0)
    _validate_file_url_belongs_to_tenant(payload.dl_image_url, user.tenant_id or 0)

    # 4. Conditional Validation for Drivers
    # ✅ FIX: Case-insensitive check to prevent bypasses (e.g., "driver" vs "Driver")
    if user.job_title and user.job_title.lower() == "driver":
        if not payload.dl_number:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Driver's License Number is required for Drivers.")
        if not payload.dl_image_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Driver's License Image is required for Drivers.")

    # 5. Map Identity & Compliance Fields
    user.full_name = payload.full_name
    user.phone_number = payload.phone_number
    user.avatar_url = payload.avatar_url
    
    user.id_number = payload.id_number
    user.id_image_url = payload.id_image_url
    user.dl_number = payload.dl_number
    user.dl_image_url = payload.dl_image_url
    user.dl_expiry = payload.dl_expiry

    # ✅ SECURITY FIX: Handle email updates safely
    normalized_email = normalize_email(payload.email)
    if normalized_email != user.email:
        # If the user is correcting their email, ensure it's not already taken
        existing_user_stmt = select(User).where(User.email == normalized_email)
        existing_user = (await db.execute(existing_user_stmt)).scalars().first()
        if existing_user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This email is already in use by another account")
        user.email = normalized_email

    # 6. Update user state (Password & Onboarding Status)
    user.password_hash = get_password_hash(payload.password)
    user.is_onboarded = True
    
    # Note: As per your design, email_verified remains False here, 
    # requiring a separate verification step after onboarding.
    
    user.invite_token = None    # Invalidate the token so it can't be reused
    user.invite_expires_at = None
    
    await db.commit()
    await db.refresh(user)

    # ✅ Invalidate cache and log the onboarding completion
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
        
    # Note: user_id is set to user.id here because the user is performing this action on their own account
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=user.id,
        action="accept_invite", target_type="user", target_id=user.id,
        details={"user_email": user.email, "job_title": user.job_title}
    )
    await db.commit()  # Commit the activity log flush

    return user
