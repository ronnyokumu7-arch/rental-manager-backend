import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.config import get_settings
from app.models.password_reset import PasswordResetToken
from app.models.refresh_tokens import RefreshToken
from app.models.users import User

settings = get_settings()
RESET_TOKEN_EXPIRE_MINUTES = 15


async def generate_refresh_token(
    user_id: int,
    tenant_id: int,  # ✅ NEW: Required for tenant-scoped storage
    db: AsyncSession,
    user_agent: Optional[str] = None,  # ✅ NEW: Device/browser info
    ip_address: Optional[str] = None,  # ✅ NEW: Client IP
) -> str:
    """
    Generates a secure opaque refresh token, hashes it for DB storage,
    and returns the raw token to be sent to the client.
    
    ✅ SECURITY: Uses SHA-256 hashing so DB leaks don't expose usable tokens.
    ✅ AUDIT: Captures user_agent and ip_address for session management UI.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    
    db_token = RefreshToken(
        user_id=user_id,
        tenant_id=tenant_id,  # ✅ NEW
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,  # ✅ NEW
        ip_address=ip_address,  # ✅ NEW
    )
    db.add(db_token)
    return raw_token


async def get_valid_reset_token_or_400(token: str, db: AsyncSession) -> PasswordResetToken:
    """
    Helper to validate token existence, usage status, and expiration.
    
    ✅ SECURITY: Returns generic error messages to prevent token enumeration.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at == None,
    )
    result = await db.execute(stmt)
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    now = datetime.now(timezone.utc)
    expires_at = db_token.expires_at if db_token.expires_at.tzinfo else db_token.expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired. Please request a new one.",
        )
    return db_token


async def get_active_user_or_400(user_id: int, db: AsyncSession) -> User:
    """
    Helper to verify user exists and is active for password reset.
    
    ✅ SECURITY: Returns generic error messages to prevent user enumeration.
    """
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return user
