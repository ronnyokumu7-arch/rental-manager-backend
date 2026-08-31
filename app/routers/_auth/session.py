import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

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

# ✅ ROTATION-RACE GRACE WINDOW: a token revoked less than this many seconds ago
# (but not expired) is treated as a concurrent-rotation race and rotated forward
# instead of 401-ing. Kills the "two parallel 401s = silent logout" death spiral.
ROTATION_GRACE_SECONDS = 60


def _refresh_candidates(request: Request, body_token: Optional[str] = None) -> List[str]:
    """
    ✅ VALID-TOKEN-WINS precedence: body first (cross-site primary), then cookie.
    Every candidate is validated; the first fully-valid one wins. A stale
    third-party cookie can no longer shadow a good body token.
    """
    candidates: List[str] = []
    if body_token:
        candidates.append(body_token)
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if cookie_token and cookie_token not in candidates:
        candidates.append(cookie_token)
    return candidates


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _load_record(db: AsyncSession, raw: str) -> Optional[RefreshToken]:
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    return (await db.execute(stmt)).scalar_one_or_none()


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
    (Unchanged — login-side eviction policy stays as designed.)
    """
    email = normalize_email(credentials.email)
    
    stmt = select(User).where(func.lower(User.email) == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

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

    if not user.password_hash.startswith("$2"):
        user.password_hash = get_password_hash(credentials.password)

    access_token = create_access_token(
        subject=str(user.id),
        claims={
            "tenant_id": user.tenant_id,
            "role": user.role,
        },
    )
    
    user_agent = request.headers.get("User-Agent", "Unknown")[:500]
    ip_address = request.client.host if request.client else None
    
    refresh_token = await generate_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        db=db,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    
    await db.commit()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )

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

    ✅ HARDENED:
    - Valid-token-wins precedence (body → cookie): stale cookies can't shadow
      a good body token (cross-site deployments).
    - Rotation-race grace window: a token revoked <60s ago (not expired) is
      rotated forward instead of 401-ing → parallel 401s no longer log users out.
    - Still revokes old token, re-checks user status, captures audit info.
    """
    candidates = _refresh_candidates(request, refresh_token)

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token found. Please log in again.",
        )

    now = datetime.now(timezone.utc)
    chosen: Optional[RefreshToken] = None
    grace_candidate: Optional[RefreshToken] = None

    # ✅ Validate ALL candidates; first fully-valid wins; remember first grace hit
    for raw in candidates:
        rec = await _load_record(db, raw)
        if not rec:
            continue
        if _as_utc(rec.expires_at) <= now:
            continue  # expired — never usable
        if not rec.revoked:
            chosen = rec
            break
        if rec.revoked_at is not None:
            if (now - _as_utc(rec.revoked_at)) <= timedelta(seconds=ROTATION_GRACE_SECONDS):
                if grace_candidate is None:
                    grace_candidate = rec

    # ✅ Rotation race (two parallel refreshes): rotate forward, don't logout
    if chosen is None and grace_candidate is not None:
        chosen = grace_candidate

    if chosen is None:
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # User status re-check
    user_stmt = select(User).where(User.id == chosen.user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if not user or not user.is_active or user.is_suspended:
        chosen.revoked = True
        chosen.revoked_at = now
        await db.commit()
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or suspended",
        )

    # ROTATION: revoke the consumed token (idempotent if already revoked via grace)
    if not chosen.revoked:
        chosen.revoked = True
        chosen.revoked_at = now

    user_agent = request.headers.get("User-Agent", "Unknown")[:500]
    ip_address = request.client.host if request.client else None

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

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )

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
    Revokes EVERY presented token (body + cookie) and clears the cookie.
    Silently succeeds even if tokens are invalid (prevents enumeration).
    """
    now = datetime.now(timezone.utc)
    revoked_any = False

    for raw in _refresh_candidates(request, refresh_token):
        rec = await _load_record(db, raw)
        if rec and not rec.revoked:
            rec.revoked = True
            rec.revoked_at = now
            revoked_any = True

    if revoked_any:
        await db.commit()

    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    return None
