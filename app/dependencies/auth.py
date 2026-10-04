# app/dependencies/auth.py
"""
✅ Core authentication dependency — JWT validation + user state checks.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ SECURITY: WWW-Authenticate headers preserved on every 401 (RFC 7235).
✅ COPY: 401s here are what the frontend refresh flow intercepts; when they
   DO surface (refresh dead), they now say "Session Expired / Log In" with a
   login action — one voice across the whole app.
"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.errors import AuthenticationError, AuthorizationError
from app.core.security import decode_access_token
from app.db.database import get_db, set_rls_context
from app.models.users import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

# ✅ RFC 7235 header preserved on all 401s
_WWW = {"WWW-Authenticate": "Bearer"}


async def _authenticate_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User:
    """
    Core authentication dependency.
    Validates JWT access token and returns the authenticated user.
    
    ✅ SECURITY: Checks for:
    - Valid Bearer scheme
    - Valid, non-expired JWT
    - Token type is 'access' (not 'refresh')
    - User exists and is active
    - User is NOT suspended
    """
    # 1. Validate Bearer scheme
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(
            title="Login Required",
            message="Please log in to continue.",
            headers=_WWW,
        )

    # 2. Decode and validate JWT
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise AuthenticationError(
            message="Your session has expired. Please log in again.",
            headers=_WWW,
        )

    # 3. ✅ CRITICAL: Verify token type is 'access' (prevents refresh token misuse)
    token_type = payload.get("type")
    if token_type != "access":
        raise AuthenticationError(
            title="Login Required",
            message="Please log in again to continue.",
            headers=_WWW,
        )

    # 4. Extract user ID from 'sub' claim
    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError(
            message="Your session has expired. Please log in again.",
            headers=_WWW,
        )

    # 5. Convert to integer safely
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        raise AuthenticationError(
            message="Your session has expired. Please log in again.",
            headers=_WWW,
        )

    # 6. Fetch user from database (async)
    await set_rls_context(db, public_user_id=user_id_int)
    result = await db.execute(select(User).where(User.id == user_id_int))
    user = result.scalar_one_or_none()

    # 7. ✅ CRITICAL: Validate user state (active AND not suspended)
    if not user:
        raise AuthenticationError(
            title="Account Unavailable",
            message="This account no longer exists. Please contact support.",
            headers=_WWW,
        )

    if not user.is_active:
        raise AuthenticationError(
            title="Account Inactive",
            message="Your account is inactive. Please contact your administrator.",
            headers=_WWW,
        )

    if user.is_suspended:
        raise AuthorizationError(
            title="Account Suspended",
            message="Your account is suspended. Please contact support.",
        )

    await set_rls_context(
        db,
        user_id=user.id,
        tenant_id=user.tenant_id,
        is_super_admin=user.role == UserRole.super_admin,
        is_investor=user.role == UserRole.investor,
    )

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await _authenticate_user(credentials, db)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    return await _authenticate_user(credentials, db)
