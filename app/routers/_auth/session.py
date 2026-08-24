import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
    - Refresh token stored in HttpOnly cookie (not accessible to JS)
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
        # Fallback for legacy plaintext passwords (should be rare)
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
    user_agent = request.headers.get("User-Agent", "Unknown")[:500]  # Truncate to model limit
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

    # ✅ Set refresh token as HttpOnly cookie (not accessible to JavaScript)
    response.set_cookie(
        key="rm_refresh_token",
        value=refresh_token,
        httponly=True,  # Cannot be accessed via JavaScript
        secure=True,    # Only sent over HTTPS (False in dev if needed)
        samesite="lax", # CSRF protection
        max_age=7 * 24 * 60 * 60,  # 7 days
        path="/",
    )

    # Return access token in response body (frontend stores in cookie)
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,  # Still return for backward compatibility
        token_type="bearer",
        user=user,
    )


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Rotates refresh tokens (prevents replay attacks).
    
    ✅ SECURITY:
    - Reads refresh token from HttpOnly cookie (not request body)
    - Validates old token before issuing new pair
    - Revokes old token immediately (one-time use)
    - Checks user status (active, not suspended)
    - Revokes token if user is banned/suspended
    - Captures device/browser info for new session
    """
    # ✅ Read refresh token from HttpOnly cookie
    refresh_token = request.cookies.get("rm_refresh_token")
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token found. Please log in again.",
        )
    
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await db.execute(stmt)
    db_token = result.scalar_one_or_none()
    
    # 1. Validate existence and revocation status
    if not db_token or db_token.revoked:
        # Security: Reused revoked token = potential replay attack
        # Clear the invalid cookie
        response.delete_cookie("rm_refresh_token", path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
        
    # 2. Validate expiration
    now = datetime.now(timezone.utc)
    expires_at = db_token.expires_at if db_token.expires_at.tzinfo else db_token.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        # Clear expired cookie
        response.delete_cookie("rm_refresh_token", path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please log in again.",
        )
        
    # 3. Fetch User to check status
    user_stmt = select(User).where(User.id == db_token.user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    
    if not user or not user.is_active or user.is_suspended:
        # User was banned/suspended after token was issued
        db_token.revoked = True
        db_token.revoked_at = now
        await db.commit()
        response.delete_cookie("rm_refresh_token", path="/")
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
    
    # ✅ Set new refresh token in HttpOnly cookie (rotation)
    response.set_cookie(
        key="rm_refresh_token",
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days
        path="/",
    )
    
    return TokenOut(
        access_token=new_access,
        refresh_token=new_refresh,  # Still return for backward compatibility
        token_type="bearer",
        user=user,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Revokes the specific refresh token provided and clears the cookie.
    
    ✅ SECURITY: 
    - Reads refresh token from HttpOnly cookie
    - Silently succeeds even if token is invalid (prevents enumeration)
    - Always clears the cookie
    """
    # ✅ Read refresh token from HttpOnly cookie
    refresh_token = request.cookies.get("rm_refresh_token")
    
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await db.execute(stmt)
        db_token = result.scalar_one_or_none()
        
        if db_token and not db_token.revoked:
            db_token.revoked = True
            db_token.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    
    # ✅ Always clear the refresh cookie
    response.delete_cookie("rm_refresh_token", path="/")
    
    return None
