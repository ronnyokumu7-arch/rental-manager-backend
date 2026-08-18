"""
Authenticated file-serving endpoint.
Replaces public StaticFiles for sensitive tenant uploads (IDs, DLs, contracts).

Serving strategy:
- Cloudinary backend → 302 redirect to a short-lived signed URL (bandwidth
  offloaded from Render; tenant access still enforced here, first hop).
- Local backend      → stream bytes via FileResponse (dev / fallback).

Signed-URL exchange:
- Browsers/<img> tags cannot send the JWT Authorization header, so the
  frontend calls GET .../signed (authenticated) to swap the stored API URL
  for a short-lived signed Cloudinary URL, then renders that.
"""
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User, UserRole
from app.services.storage import get_backend

router = APIRouter(prefix="/files", tags=["files"])
settings = get_settings()

# ✅ Signed URLs live for 10 minutes — enough to view, too short to leak.
SIGNED_URL_TTL_SECONDS = 600

# ✅ SECURITY: Valid categories (prevents arbitrary folder access)
VALID_CATEGORIES = {"avatar", "compliance", "contract", "misc"}


def _get_upload_dir() -> Path:
    """Returns the configured upload directory."""
    upload_dir = Path(settings.uploads_dir).resolve()
    return upload_dir


def _enforce_access(current_user: User, tenant_id: int, category: str, filename: str) -> None:
    """
    ✅ Shared safety checks for both routes:
    - Multi-tenancy enforcement (super admin bypasses)
    - Category allowlist
    - Filename path-traversal guard
    """
    if current_user.role != UserRole.super_admin:
        if current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to files from this tenant"
            )

    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file category"
        )

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid filename"
        )


@router.get("/tenant_{tenant_id}/{category}/{filename}")
@limiter.limit("120/minute")
async def serve_secure_file(
    request: Request,
    tenant_id: int,
    category: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Serve a file ONLY if the authenticated user has access to the tenant that owns it.

    Access rules:
    - Super admins: can access any tenant's files
    - Tenant users: can ONLY access their own tenant's files
    - Unauthenticated: blocked (enforced by get_current_user dependency)
    """
    _enforce_access(current_user, tenant_id, category, filename)

    # ✅ CLOUDINARY PATH: redirect to a short-lived signed URL.
    # The tenant check above already ran, so the redirect inherits it.
    relative_path = f"tenant_{tenant_id}/{category}/{filename}"
    signed = get_backend().signed_url(relative_path, ttl_seconds=SIGNED_URL_TTL_SECONDS)
    if signed:
        return RedirectResponse(
            url=signed,
            status_code=status.HTTP_302_FOUND,
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )

    # ─── LOCAL DISK FALLBACK (unchanged) ────────────────────────────────────
    upload_dir = _get_upload_dir()
    file_path = (upload_dir / f"tenant_{tenant_id}" / category / filename).resolve()

    # ✅ FINAL SAFETY CHECK: Ensure resolved path is strictly inside upload_dir
    try:
        file_path.relative_to(upload_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: invalid file path"
        )

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Determine content type safely
    content_type, _ = mimetypes.guess_type(str(file_path))
    if not content_type:
        content_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        }
    )


@router.get("/tenant_{tenant_id}/{category}/{filename}/signed")
@limiter.limit("120/minute")
async def get_signed_file_url(
    request: Request,
    tenant_id: int,
    category: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ✅ SIGNED-URL EXCHANGE for private assets.

    Browsers and <img> tags cannot send the JWT Authorization header, so the
    frontend calls this authenticated endpoint to swap the stored API URL for
    a short-lived signed Cloudinary URL, then renders that.

    Same tenant-isolation checks as the serving endpoint.
    """
    _enforce_access(current_user, tenant_id, category, filename)

    signed = get_backend().signed_url(
        f"tenant_{tenant_id}/{category}/{filename}",
        ttl_seconds=SIGNED_URL_TTL_SECONDS,
    )
    if not signed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signed URLs unavailable for this storage backend"
        )

    return {"url": signed, "ttl_seconds": SIGNED_URL_TTL_SECONDS}
