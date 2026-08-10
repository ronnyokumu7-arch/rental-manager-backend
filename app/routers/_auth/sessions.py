"""
Sessions Management Router
Handles session visibility and revocation for authenticated users.

Endpoints:
- GET /sessions — List current user's active sessions
- DELETE /sessions/{session_id} — Revoke a specific session
- DELETE /sessions/all — Revoke all sessions except current (panic button)
- GET /sessions/admin/{user_id} — Super admin view of a user's sessions
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _get_current_token_hash(refresh_token: Optional[str]) -> Optional[str]:
    """Hash the current refresh token for comparison."""
    if not refresh_token:
        return None
    return hashlib.sha256(refresh_token.encode()).hexdigest()


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
    current_refresh_token: Optional[str] = Query(
        None,
        description="Pass your current refresh token to mark it as 'is_current' in the response",
    ),
    include_revoked: bool = Query(False, description="Include revoked/expired sessions"),
    page: int = Query(1, ge=1),                      # ✅ FIXED: was missing
    page_size: int = Query(50, ge=1, le=200),        # ✅ FIXED: was missing
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all sessions for the current user.
    
    ✅ SECURITY:
    - Tenant-scoped (defense in depth)
    - Only returns sessions belonging to the authenticated user
    - Optional `current_refresh_token` param marks the active session
    
    ✅ USE CASE: "Where am I logged in?" UI
    """
    sessions = await _get_user_sessions(
        db=db,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        active_only=not include_revoked,
    )
    
    # Mark current session if token provided
    current_hash = _get_current_token_hash(current_refresh_token)
    
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Revoke a specific session (e.g., "Log out that Chrome session on Windows").
    
    ✅ SECURITY:
    - Session must belong to current user (or super admin)
    - Session must be in current user's tenant
    - Cannot revoke the current session via this endpoint (use /auth/logout instead)
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
    current_refresh_token: str = Query(
        ...,
        description="Your current refresh token — this session will be preserved",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Revoke ALL sessions except the current one (panic button for compromised accounts).
    
    ✅ SECURITY:
    - Requires the current refresh token to identify which session to keep
    - Tenant-scoped
    - Logs the mass revocation for audit trail
    
    ✅ USE CASE: "I think my account was compromised — log out everything else"
    """
    current_hash = _get_current_token_hash(current_refresh_token)
    if not current_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid current refresh token",
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
