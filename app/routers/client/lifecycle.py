# app/routers/client/lifecycle.py
"""
✅ CLIENT LIFECYCLE — activate / suspend / reactivate.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B): activation KYC gate now returns field_errors so the form
   can highlight exactly which document is missing.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.subscription import require_active_subscription
from app.models.users import User
from app.models.clients import Client, ClientStatus
from app.schemas.client import ClientOut
from app.services.cache import invalidate_client_cache
from ._helpers import get_authorized_client_async

router = APIRouter()


# ---------------------------------------------------------------------------
# LIFECYCLE STATE CHANGES
# ---------------------------------------------------------------------------

@router.post("/{client_id}/activate", response_model=ClientOut)
@limiter.limit("15/minute")
async def activate_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)
    
    if client.status == ClientStatus.active:
        raise BadRequestError(
            title="Already Active",
            message="This client is already active.",
        )
    
    # ✅ KYC GATE: field-level errors so the form highlights what's missing
    missing_docs: dict[str, str] = {}
    if not client.id_image_front:
        missing_docs["id_image_front"] = "A photo of the client's ID is required"
    if not client.dl_image_front:
        missing_docs["dl_image_front"] = "A photo of the driver's licence is required"
    if missing_docs:
        raise BadRequestError(
            title="Missing Required Documents",
            message="Add photos of the client's ID and driver's licence before activating them.",
            field_errors=missing_docs,
        )
        
    client.status = ClientStatus.active
    await db.commit()
    await db.refresh(client)
    
    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)
    
    return client


@router.post("/{client_id}/suspend", response_model=ClientOut)
@limiter.limit("15/minute")
async def suspend_client(
    request: Request,
    client_id: int,
    reason: str = "Violation of terms",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)
    
    if client.status == ClientStatus.suspended:
        raise BadRequestError(
            title="Already Suspended",
            message="This client is already suspended.",
        )
        
    client.status = ClientStatus.suspended
    await db.commit()
    await db.refresh(client)
    
    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)
    
    return client


@router.post("/{client_id}/reactivate", response_model=ClientOut)
@limiter.limit("15/minute")
async def reactivate_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)
    
    if client.status != ClientStatus.suspended:
        raise BadRequestError(
            title="Not Suspended",
            message="This client isn't suspended, so they can't be reactivated.",
        )
        
    client.status = ClientStatus.active
    await db.commit()
    await db.refresh(client)
    
    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)
    
    return client
