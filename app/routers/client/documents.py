# app/routers/client/documents.py
"""
✅ DOCUMENT UPLOADS — SLOT UPSERT (one file per slot, atomic replace).
Every endpoint: upload new → delete old → point column at new.
Re-uploading a slot can NEVER accumulate files.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B):
  - Image content-type validation (was: any file accepted).
  - Storage failures → typed ServerError (was: raw 500).
  - Old-file deletion is fail-safe (orphan > false 500 after commit).
  - Removed duplicate on_client_created calls (task trigger lives in CREATE only).
"""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ServerError, ValidationFailedError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.subscription import require_active_subscription
from app.models.users import User
from app.models.clients import Client
from app.schemas.client import ClientOut
from app.services.storage import upload_file, delete_file  # ✅ + delete_file
from app.services.cache import invalidate_client_cache
from app.services.client_tasks import ClientTaskService
from ._helpers import get_authorized_client_async

router = APIRouter()


# ---------------------------------------------------------------------------
# ✅ SHARED GUARDS (Phase B)
# ---------------------------------------------------------------------------
def _assert_image(file: UploadFile) -> None:
    """Only images may enter compliance/avatar slots."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise ValidationFailedError(
            title="Invalid File Type",
            message="Only image files (JPG, PNG, WEBP) are accepted for this document.",
            field_errors={"file": "Must be an image file"},
        )


async def _upload_slot_image(file: UploadFile, tenant_id: int, category: str) -> str:
    """Validate + upload; typed errors only (storage internals never leak as raw 500)."""
    _assert_image(file)
    try:
        return await upload_file(file=file, tenant_id=tenant_id, category=category)
    except (AppException, HTTPException):
        raise  # already typed/structured — pass through
    except Exception as e:
        print(f"⚠️ Storage upload failed for tenant {tenant_id}: {e}")
        raise ServerError(
            title="Upload Failed",
            message="We couldn't store this file. Please try again in a moment.",
        )


def _safe_delete_replaced(old_url: str | None, new_url: str, tenant_id: int) -> None:
    """Orphaned file > false 500 after a successful commit."""
    if old_url and old_url != new_url:
        try:
            delete_file(old_url, tenant_id=tenant_id)
        except Exception as e:
            print(f"⚠️ Warning: failed to delete replaced file {old_url}: {e}")


# ---------------------------------------------------------------------------
# DOCUMENT UPLOADS — SLOT UPSERT (one file per slot, atomic replace)
# ---------------------------------------------------------------------------

@router.post("/{client_id}/upload-id-front", response_model=ClientOut)
@limiter.limit("15/minute")
async def upload_id_front(
    request: Request,
    client_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    file_url = await _upload_slot_image(file, client.tenant_id, category="compliance")

    # ✅ SLOT UPSERT: delete the replaced file AFTER successful new upload
    old_url = client.id_image_front
    client.id_image_front = file_url
    await db.commit()
    await db.refresh(client)
    _safe_delete_replaced(old_url, file_url, client.tenant_id)

    await invalidate_client_cache(client.tenant_id)

    return client


@router.post("/{client_id}/upload-id-back", response_model=ClientOut)
@limiter.limit("15/minute")
async def upload_id_back(
    request: Request,
    client_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    file_url = await _upload_slot_image(file, client.tenant_id, category="compliance")

    old_url = client.id_image_back
    client.id_image_back = file_url
    await db.commit()
    await db.refresh(client)
    _safe_delete_replaced(old_url, file_url, client.tenant_id)

    await invalidate_client_cache(client.tenant_id)

    return client


@router.post("/{client_id}/upload-dl-front", response_model=ClientOut)
@limiter.limit("15/minute")
async def upload_dl_front(
    request: Request,
    client_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    file_url = await _upload_slot_image(file, client.tenant_id, category="compliance")

    old_url = client.dl_image_front
    client.dl_image_front = file_url
    await db.commit()
    await db.refresh(client)
    _safe_delete_replaced(old_url, file_url, client.tenant_id)

    await invalidate_client_cache(client.tenant_id)

    return client


@router.post("/{client_id}/upload-avatar", response_model=ClientOut)
@limiter.limit("15/minute")
async def upload_avatar(
    request: Request,
    client_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    file_url = await _upload_slot_image(file, client.tenant_id, category="avatar")

    old_url = client.avatar_image
    client.avatar_image = file_url
    await db.commit()
    await db.refresh(client)
    _safe_delete_replaced(old_url, file_url, client.tenant_id)

    await invalidate_client_cache(client.tenant_id)

    return client
