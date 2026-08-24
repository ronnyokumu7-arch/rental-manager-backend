from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

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
# DOCUMENT UPLOADS — SLOT UPSERT (one file per slot, atomic replace)
# Every endpoint: upload new → delete old → point column at new.
# Re-uploading a slot can NEVER accumulate files.
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

    file_url = await upload_file(
        file=file,
        tenant_id=client.tenant_id,
        category="compliance"
    )

    # ✅ SLOT UPSERT: delete the replaced file AFTER successful new upload
    old_url = client.id_image_front
    client.id_image_front = file_url
    await db.commit()
    await db.refresh(client)
    if old_url and old_url != file_url:
        delete_file(old_url, tenant_id=client.tenant_id)

    await ClientTaskService.on_client_created(db, client, client.tenant_id)
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

    file_url = await upload_file(
        file=file,
        tenant_id=client.tenant_id,
        category="compliance"
    )

    old_url = client.id_image_back
    client.id_image_back = file_url
    await db.commit()
    await db.refresh(client)
    if old_url and old_url != file_url:
        delete_file(old_url, tenant_id=client.tenant_id)

    await ClientTaskService.on_client_created(db, client, client.tenant_id)
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

    file_url = await upload_file(
        file=file,
        tenant_id=client.tenant_id,
        category="compliance"
    )

    old_url = client.dl_image_front
    client.dl_image_front = file_url
    await db.commit()
    await db.refresh(client)
    if old_url and old_url != file_url:
        delete_file(old_url, tenant_id=client.tenant_id)

    await ClientTaskService.on_client_created(db, client, client.tenant_id)
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

    file_url = await upload_file(
        file=file,
        tenant_id=client.tenant_id,
        category="avatar"
    )

    old_url = client.avatar_image
    client.avatar_image = file_url
    await db.commit()
    await db.refresh(client)
    if old_url and old_url != file_url:
        delete_file(old_url, tenant_id=client.tenant_id)

    await invalidate_client_cache(client.tenant_id)

    return client
