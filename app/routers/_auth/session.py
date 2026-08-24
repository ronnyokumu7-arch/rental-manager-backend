import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Body, status
from passlib.exc import UnknownHashError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.security import (
    create_access_token,
    get_password_hash,
    normalize_email,
    verify_password,
)
from app.db.database import get_db
from app.models.refresh_tokens import RefreshToken
from app.models.users import User
from app.schemas.auth import LoginRequest, TokenOut
from ._helpers import generate_refresh_token

router = APIRouter()
settings = get_settings()

REFRESH_COOKIE_NAME = "rm_refresh_token"


def _read_refresh_token(request: Request, body_token: Optional[str] = None) -> Optional[str]:
    """
    Read refresh token from HttpOnly cookie first, fall back to request body.
    Supports both same-site deployments (cookie works) and cross-site
    deployments where the cookie is blocked by browser policies.
    """
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return body_token


@router.post("/login", response_model=TokenOut)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    credentials: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate user and issue access + refresh tokens.
    
    ✅ SECURITY:
    - EmailStr in schema ensures valid format before DB query
    - Generic error message prevents user enumeration
    - Legacy password upgrade for plaintext → bcrypt migration
    - Captures device/browser info for session management UI
    - Refresh token stored in HttpOnly cookie AND returned in body (cross-site fallback)
    """
    # ✅ Schema validation ensures email is valid format
    email = normalize_email(credentials.email)
    
    stmt = select(User).where(func.lower(User.email) == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Verify password with legacy fallback
    password_matches = False
    try:
        password_matches = verify_password(credentials.password, user.password_hash)
    except (UnknownHashError, ValueError, TypeError):
        password_matches = credentials.password == user.password_hash

    if not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Check user state
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    if user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended. Please contact your administrator.",
        )

    # ✅ Upgrade legacy plaintext passwords to bcrypt
    if not user.password_hash.startswith("$2"):
        user.password_hash = get_password_hash(credentials.password)

    # Generate token pair
    access_token = create_access_token(
        subject=str(user.id),
        claims={
            "tenant_id": user.tenant_id,
            "role": user.role,
        },
    )
    
    # ✅ Capture device and IP info for session management
    user_agent = request.headers.get("User-Agent", "Unknown")[:500]
    ip_address = request.client.host if request.client else None
    
    # ✅ Generate refresh token with audit info
    refresh_token = await generate_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        db=db,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    
    # Commit password upgrade (if any) and new refresh token
    await db.commit()

    # ✅ Set refresh token as HttpOnly cookie (works for same-site deployments)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )

    # Return BOTH tokens in body (cross-site fallback uses these)
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=user,
    )


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Rotates refresh tokens (prevents replay attacks).
    
    ✅ SECURITY:
    - Reads refresh token from HttpOnly cookie OR request body
    - Validates old token before issuing new pair
    - Revokes old token immediately (one-time use)
    - Checks user status (active, not suspended)
    - Captures device/browser info for new session
    """
    # ✅ Read from cookie (same-site) or body (cross-site)
    token = _read_refresh_token(request, refresh_token)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token found. Please log in again.",
        )
    
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await db.execute(stmt)
    db_token = result.scalar_one_or_none()
    
    # 1. Validate existence and revocation status
    if not db_token or db_token.revoked:
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
        
    # 2. Validate expiration
    now = datetime.now(timezone.utc)
    expires_at = db_token.expires_at if db_token.expires_at.tzinfo else db_token.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please log in again.",
        )
        
    # 3. Fetch User to check status
    user_stmt = select(User).where(User.id == db_token.user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    
    if not user or not user.is_active or user.is_suspended:
        db_token.revoked = True
        db_token.revoked_at = now
        await db.commit()
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or suspended",
        )
        
    # 4. ROTATION: Revoke the old token
    db_token.revoked = True
    db_token.revoked_at = now
    
    # 5. ✅ Capture device and IP info for new session
    user_agent = request.headers.get("User-Agent", "Unknown")[:500]
    ip_address = request.client.host if request.client else None
    
    # 6. Issue NEW pair with audit info
    new_access = create_access_token(
        subject=str(user.id),
        claims={"tenant_id": user.tenant_id, "role": user.role}
    )
    new_refresh = await generate_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        db=db,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    
    await db.commit()
    
    # ✅ Set new refresh token in HttpOnly cookie (rotation, same-site benefit)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    
    # Return BOTH tokens in body (cross-site fallback)
    return TokenOut(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
        user=user,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def logout(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Revokes the specific refresh token provided and clears the cookie.
    
    ✅ SECURITY: 
    - Reads refresh token from cookie OR body (cross-site support)
    - Silently succeeds even if token is invalid (prevents enumeration)
    - Always clears the cookie
    """
    token = _read_refresh_token(request, refresh_token)
    
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await db.execute(stmt)
        db_token = result.scalar_one_or_none()
        
        if db_token and not db_token.revoked:
            db_token.revoked = True
            db_token.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    
    # ✅ Always clear the refresh cookie (harmless if not set)
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    
    return None
