# app/routers/contract/_helpers.py
"""
✅ Shared tenant-isolation guards + eager-load options for contract endpoints.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ SECURITY: the 404 copy intentionally conflates "not found" and "no access"
   to prevent contract-ID enumeration — preserved as-is.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AuthorizationError, NotFoundError
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
            raise AuthorizationError(
                title="No Agency Linked",
                message="Your account isn't linked to an agency. Contact your administrator for access.",
            )
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(
            Contract.id == contract_id,
            Contract.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    contract = result.scalars().unique().first()
    if not contract:
        raise NotFoundError(
            title="Contract Not Found",
            message="We couldn't find this contract, or you may not have access to it.",
        )
    return contract


async def get_authorized_contract_async(contract_id: int, user: User, db: AsyncSession) -> Contract:
    """Async helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(Contract.id == contract_id)
    else:
        if user.tenant_id is None:
            raise AuthorizationError(
                title="No Agency Linked",
                message="Your account isn't linked to an agency. Contact your administrator for access.",
            )
        stmt = select(Contract).options(*CONTRACT_EAGER_LOAD).where(
            Contract.id == contract_id,
            Contract.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    contract = result.scalars().unique().first()
    if not contract:
        raise NotFoundError(
            title="Contract Not Found",
            message="We couldn't find this contract, or you may not have access to it.",
        )
    return contract
