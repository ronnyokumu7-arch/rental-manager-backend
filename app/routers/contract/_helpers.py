from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.contracts import Contract
from app.models.users import User, UserRole


def get_authorized_contract(contract_id: int, user: User, db: Session) -> Contract:
    """Synchronous helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Contract).where(Contract.id == contract_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant association")
        stmt = select(Contract).where(
            Contract.id == contract_id,
            Contract.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    contract = result.scalars().first()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found or access denied")
    return contract


async def get_authorized_contract_async(contract_id: int, user: User, db: AsyncSession) -> Contract:
    """Async helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Contract).where(Contract.id == contract_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant association")
        stmt = select(Contract).where(
            Contract.id == contract_id,
            Contract.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    contract = result.scalars().first()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found or access denied")
    return contract
