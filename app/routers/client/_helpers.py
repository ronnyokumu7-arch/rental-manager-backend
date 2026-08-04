from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.users import User, UserRole
from app.models.clients import Client


# ---------------------------------------------------------------------------
# Synchronous Helper (Keep for legacy code, background tasks, or scheduler)
# ---------------------------------------------------------------------------
def get_authorized_client(client_id: int, user: User, db: Session) -> Client:
    """
    Synchronous version for non-async contexts.
    Enforces tenant isolation: tenant users can only access their own clients.
    Super admins can access any client.
    """
    if user.role == UserRole.super_admin:
        stmt = select(Client).where(Client.id == client_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Client).where(
            Client.id == client_id,
            Client.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    client = result.scalars().first()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found or access denied"
        )
    return client


# ---------------------------------------------------------------------------
# Asynchronous Helper (Use for all high-traffic API endpoints)
# ---------------------------------------------------------------------------
async def get_authorized_client_async(client_id: int, user: User, db: AsyncSession) -> Client:
    """
    Async version for high-traffic endpoints.
    Enforces tenant isolation: tenant users can only access their own clients.
    Super admins can access any client.
    """
    if user.role == UserRole.super_admin:
        stmt = select(Client).where(Client.id == client_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Client).where(
            Client.id == client_id,
            Client.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    client = result.scalars().first()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found or access denied"
        )
    return client
