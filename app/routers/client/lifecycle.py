from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client is already active."
        )
    
    if not client.id_image_front or not client.dl_image_front:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot activate client. ID and DL photos are required."
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client is already suspended."
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only suspended clients can be reactivated."
        )
        
    client.status = ClientStatus.active
    await db.commit()
    await db.refresh(client)
    
    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)
    
    return client
