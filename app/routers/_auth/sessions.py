"""
Sessions Management Router
Handles session visibility and revocation for authenticated users.

Endpoints:
- GET /sessions — List current user's active sessions
- DELETE /sessions/{session_id} — Revoke a specific session
- DELETE /sessions/all — Revoke all sessions except current (panic button)
- GET /sessions/admin/{user_id} — Super admin view of a user's sessions

✅ SECURITY MODEL:
The current session is identified via VALID-TOKEN-WINS resolution:
  candidates = [body refresh_token (cross-site primary), HttpOnly cookie]
  → the first candidate whose DB record is ACTIVE (not revoked, not expired)
    is treated as the current session.
  A stale third-party cookie can no longer shadow the real session —
  the panic button can never preserve a dead cookie session while
  revoking every live device.

The token is NEVER passed via query params, so it never appears in URLs,
logs, referrer headers, or browser history.

✅ HARDENED (this revision):
- _resolve_current_token_hash: valid-token-wins current-session resolver.
- revoke_session: cannot revoke the CURRENT session (use /auth/logout).
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.refresh_tokens import RefreshToken
from app.models.users import User, UserRole
from app.schemas.auth import SessionOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.activity_log import ActivityLogService

router = APIRouter()

# ✅ Must match the cookie name set in session.py
REFRESH_COOKIE_NAME = "rm_refresh_token"


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

async def _resolve_current_token_hash(
    request: Request,
    body_token: Optional[str],
    db: AsyncSession,
) -> Optional[str]:
    """
    ✅ VALID-TOKEN-WINS current-session resolver.

    Candidates (in order): body token (cross-site primary), then HttpOnly cookie.
    The first candidate whose DB record is ACTIVE (exists, not revoked, not
    expired) is returned as the current session hash.

    Returns None when no candidate is active — callers decide the policy
    (401 for the panic button, is_current=False for listing).
    """
    now = datetime.now(timezone.utc)
    candidates = []
    if body_token:
        candidates.append(body_token)
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if cookie_token and cookie_token not in candidates:
        candidates.append(cookie_token)

    for raw in candidates:
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        rec = (await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )).scalar_one_or_none()
        if rec and not rec.revoked and rec.expires_at > now:
            return token_hash
    return None


async def _get_user_sessions(
    db: AsyncSession,
    user_id: int,
    tenant_id: Optional[int] = None,
    active_only: bool = True,
) -> list[RefreshToken]:
    """Fetch sessions for a user with optional tenant scoping."""
    stmt = select(RefreshToken).where(RefreshToken.user_id == user_id)
    
    if tenant_id is not None:
        stmt = stmt.where(RefreshToken.tenant_id == tenant_id)
    
    if active_only:
        stmt = stmt.where(
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    
    stmt = stmt.order_by(RefreshToken.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=PaginatedResponse[SessionOut])
@limiter.limit("30/minute")
async def list_my_sessions(
    request: Request,
    include_revoked: bool = Query(False, description="Include revoked/expired sessions"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    refresh_token: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all sessions for the current user.
    
    ✅ SECURITY:
    - Tenant-scoped (defense in depth)
    - Only returns sessions belonging to the authenticated user
    - Current session identified via valid-token-wins resolver
    
    ✅ USE CASE: "Where am I logged in?" UI
    """
    sessions = await _get_user_sessions(
        db=db,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        active_only=not include_revoked,
    )
    
    # ✅ Mark current session using the ACTIVE token (body → cookie)
    current_hash = await _resolve_current_token_hash(request, refresh_token, db)
    
    session_items = [
        SessionOut(
            id=s.id,
            user_id=s.user_id,
            user_agent=s.user_agent,
            ip_address=s.ip_address,
            created_at=s.created_at,
            expires_at=s.expires_at,
            revoked=s.revoked,
            revoked_at=s.revoked_at,
            is_current=(current_hash is not None and s.token_hash == current_hash),
        )
        for s in sessions
    ]
    return paginate_items(session_items, total=len(session_items), page=page, page_size=page_size)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def revoke_session(
    request: Request,
    session_id: int,
    refresh_token: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Revoke a specific session (e.g., "Log out that Chrome session on Windows").
    
    ✅ SECURITY:
    - Session must belong to current user (or super admin)
    - Session must be in current user's tenant
    - ✅ HARDENED: cannot revoke the CURRENT session (use /auth/logout)
    """
    # Fetch session with tenant isolation
    stmt = select(RefreshToken).where(
        RefreshToken.id == session_id,
    )
    
    if current_user.role != UserRole.super_admin:
        # ✅ CRITICAL: Tenant users can only revoke their own sessions in their tenant
        stmt = stmt.where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.tenant_id == current_user.tenant_id,
        )
    
    result = await db.execute(stmt)
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    
    # ✅ HARDENED: block self-revocation via this endpoint
    current_hash = await _resolve_current_token_hash(request, refresh_token, db)
    if current_hash is not None and session.token_hash == current_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /auth/logout to end the current session.",
        )
    
    if session.revoked:
        # Idempotent — already revoked
        return None
    
    now = datetime.now(timezone.utc)
    session.revoked = True
    session.revoked_at = now
    await db.commit()
    
    # ✅ Log the revocation
    await ActivityLogService.log(
        db=db,
        tenant_id=session.tenant_id,
        user_id=current_user.id,
        action="revoke_session",
        target_type="session",
        target_id=session.id,
        details={
            "revoked_user_id": session.user_id,
            "ip_address": session.ip_address,
        },
    )
    
    return None


@router.delete("/sessions/all", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")  # 🚨 STRICT: Panic button — limit to prevent abuse
async def revoke_all_sessions_except_current(
    request: Request,
    refresh_token: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Revoke ALL sessions except the current one (panic button for compromised accounts).
    
    ✅ SECURITY:
    - ✅ HARDENED: current session identified via valid-token-wins resolver —
      a stale cookie can no longer be preserved while live sessions die.
    - Tenant-scoped
    - Logs the mass revocation for audit trail
    
    ✅ USE CASE: "I think my account was compromised — log out everything else"
    ✅ NOTE: cross-site clients MUST send the refresh_token in the body so the
    resolver can identify the live session (third-party cookies are blocked).
    """
    # ✅ Identify the ACTIVE session to preserve (body → cookie)
    current_hash = await _resolve_current_token_hash(request, refresh_token, db)
    if not current_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active session found. Please log in again.",
        )
    
    now = datetime.now(timezone.utc)
    
    # ✅ Revoke all active sessions EXCEPT the current one
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.tenant_id == current_user.tenant_id,
            RefreshToken.revoked == False,
            RefreshToken.token_hash != current_hash,
        )
        .values(revoked=True, revoked_at=now)
    )
    
    result = await db.execute(stmt)
    revoked_count = result.rowcount
    await db.commit()
    
    # ✅ Log the mass revocation
    await ActivityLogService.log(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="revoke_all_sessions",
        target_type="user",
        target_id=current_user.id,
        details={
            "revoked_count": revoked_count,
            "reason": "Mass session revocation (panic button)",
        },
    )
    
    return {
        "message": f"Successfully revoked {revoked_count} session(s)",
        "revoked_count": revoked_count,
    }


@router.get("/sessions/admin/{user_id}", response_model=PaginatedResponse[SessionOut])
@limiter.limit("30/minute")
async def list_user_sessions_admin(
    request: Request,
    user_id: int,
    include_revoked: bool = Query(False, description="Include revoked/expired sessions"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Super admin endpoint: View all sessions for a specific user.
    ✅ SECURITY:
    - Requires super_admin role
    - Tenant-scoped (super admin can view any tenant's users)
    - Used for support/debugging
    """
    if current_user.role != UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    
    # Verify target user exists
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    target_user = user_result.scalars().first()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    sessions = await _get_user_sessions(
        db=db,
        user_id=user_id,
        tenant_id=target_user.tenant_id,  # ✅ Scope to target user's tenant
        active_only=not include_revoked,
    )
    
    session_items = [
        SessionOut(
            id=s.id,
            user_id=s.user_id,
            user_agent=s.user_agent,
            ip_address=s.ip_address,
            created_at=s.created_at,
            expires_at=s.expires_at,
            revoked=s.revoked,
            revoked_at=s.revoked_at,
            is_current=False,  # Admin view doesn't know which is current
        )
        for s in sessions
    ]
    return paginate_items(session_items, total=len(session_items), page=page, page_size=page_size)
