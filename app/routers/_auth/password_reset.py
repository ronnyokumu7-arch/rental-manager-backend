import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.security import get_password_hash, normalize_email, verify_password
from app.db.database import get_db
from app.models.password_reset import PasswordResetToken
from app.models.refresh_tokens import RefreshToken
from app.models.users import User
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest
from app.services.activity_log import ActivityLogService
from app.services.email import send_password_reset_email, send_password_reset_success
from ._helpers import get_active_user_or_400, get_valid_reset_token_or_400

router = APIRouter()
settings = get_settings()
RESET_TOKEN_EXPIRE_MINUTES = 15


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate password reset flow.
    
    ✅ SECURITY:
    - EmailStr in schema ensures valid format before DB query
    - Generic response prevents user enumeration
    - Deletes any existing unused tokens before creating new one
    - Token is hashed before storage (SHA-256)
    """
    # ✅ Schema validation ensures email is valid format
    email = normalize_email(payload.email)
    
    stmt = select(User).where(func.lower(User.email) == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    # ✅ CRITICAL: Return generic message even if user doesn't exist (prevents enumeration)
    if not user or not user.is_active:
        return {"message": "If that email exists, a reset link has been sent"}

    # Delete any existing unused tokens for this user
    delete_stmt = delete(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at == None,
    )
    await db.execute(delete_stmt)
    await db.commit()

    # Generate new token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    db_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_token)
    await db.commit()

    # Send email with reset link
    reset_link = f"{settings.frontend_url}/reset-password?token={raw_token}"
    send_password_reset_email(
        to=user.email,
        full_name=user.full_name,
        reset_link=reset_link,
    )

    return {"message": "If that email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Complete password reset flow.
    
    ✅ SECURITY:
    - Validates token existence, usage status, and expiration
    - Verifies user is active before allowing reset
    - Prevents password reuse
    - ✅ REVOKES ALL ACTIVE SESSIONS (enforces LOGOUT_ON_PASSWORD_CHANGE)
    - Marks token as used after successful reset
    - Sends confirmation email to user
    - Schema enforces password strength requirements
    - Audit-logged for forensic trail
    """
    db_token = await get_valid_reset_token_or_400(payload.token, db)
    user = await get_active_user_or_400(db_token.user_id, db)

    # ✅ Prevent password reuse
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from your current password.",
        )

    # Update password and mark token as used
    user.password_hash = get_password_hash(payload.new_password)
    db_token.used_at = datetime.now(timezone.utc)

    # ✅ CRITICAL: Kill ALL active sessions for this user.
    # A password reset implies potential account compromise — any existing
    # refresh token (including an attacker's) must not survive the reset.
    now = datetime.now(timezone.utc)
    revoke_result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,
        )
        .values(revoked=True, revoked_at=now)
    )
    revoked_count = revoke_result.rowcount

    # ✅ Defense in depth: purge any other unused reset tokens
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at == None,
        )
    )

    await db.commit()

    # ✅ Audit log for forensic trail
    await ActivityLogService.log(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="password_reset",
        target_type="user",
        target_id=user.id,
        details={"revoked_sessions": revoked_count},
    )

    # Send confirmation email
    send_password_reset_success(
        to=user.email,
        full_name=user.full_name,
    )

    return {"message": "Password reset successfully. You can now log in with your new password."}
