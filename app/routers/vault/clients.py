# app/routers/vault/clients.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.clients import Client
from app.models.users import User
from app.schemas.client import ClientOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import invalidate_client_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/clients", tags=["vault-clients"])

@router.get("/", response_model=PaginatedResponse[ClientOut])
@limiter.limit("60/minute")
async def list_vault_clients(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch clients that are explicitly archived
    stmt = select(Client).where(
        Client.tenant_id == current_user.tenant_id,
        Client.is_archived == True
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            Client.full_name.ilike(search_lower) |
            Client.phone.ilike(search_lower) |
            Client.id_number.ilike(search_lower)
        )
        
    stmt = stmt.order_by(Client.archived_at.desc().nullslast(), Client.created_at.desc())
    
    result = await db.execute(stmt)
    clients = result.scalars().all()
    return paginate_items(clients, total=len(clients), page=page, page_size=page_size)

@router.post("/{client_id}/restore", response_model=ClientOut)
@limiter.limit("10/minute")
async def restore_vault_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Client).where(
        Client.id == client_id,
        Client.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    client = result.scalars().first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Client not found in vault")
        
    # Restore logic: Flip the archive flag
    client.is_archived = False
    client.archived_at = None
    
    await db.commit()
    await db.refresh(client)

    # ✅ Invalidate client cache so the restored client appears in active lists
    await invalidate_client_cache(current_user.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_client", target_type="client", target_id=client.id,
        details={"client_name": client.full_name}
    )
    await db.commit()  # Commit the activity log flush

    return client

@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Client).where(
        Client.id == client_id,
        Client.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    client = result.scalars().first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Client not found in vault")
        
    # Capture details before permanent deletion
    client_name = client.full_name
        
    # Hard delete: Permanent destruction from the database
    await db.delete(client)
    await db.commit()

    # ✅ Invalidate client cache
    await invalidate_client_cache(current_user.tenant_id)
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_client", target_type="client", target_id=client_id,
        details={"client_name": client_name}
    )
    await db.commit()  # Commit the activity log flush
