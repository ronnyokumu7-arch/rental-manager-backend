# app/routers/_helpers.py
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.models.bookings import Booking
from app.models.contracts import Contract
from app.models.users import User, UserRole

# ✅ FIXED: Shared eager-loading options — ContractOut serialization and
# generate_contract_pdf both need booking → client/vehicle pre-loaded.
# Without this, async lazy-loading raises MissingGreenlet (500 after commit).
CONTRACT_EAGER_LOAD = (
    selectinload(Contract.booking).selectinload(Booking.client),
    selectinload(Contract.booking).selectinload(Booking.vehicle),
)


def get_authorized_contract(contract_id: int, user: User, db: Session) -> Contract:
    """Synchronous helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(Contract.id == contract_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant association")
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(
            Contract.id == contract_id,
            Contract.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    contract = result.scalars().unique().first()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found or access denied")
    return contract


async def get_authorized_contract_async(contract_id: int, user: User, db: AsyncSession) -> Contract:
    """Async helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(Contract.id == contract_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant association")
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(
            Contract.id == contract_id,
            Contract.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    contract = result.scalars().unique().first()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found or access denied")
    return contract
