from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking
from app.models.contracts import Contract, ContractStatus
from app.models.users import User
from app.schemas.contract import ContractOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import get_cached_contract_list, set_cached_contract_list, invalidate_contract_cache
from app.services.contract_pdf import generate_contract_pdf
from ._helpers import get_authorized_contract_async

router = APIRouter()
settings = get_settings()


@router.get("/", response_model=PaginatedResponse[ContractOut])
@limiter.limit("60/minute")
async def list_contracts(
    request: Request,
    booking_id: int | None = None,
    contract_status: ContractStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ✅ Tenant-scoped caching
    cached = await get_cached_contract_list(current_user.tenant_id, booking_id, contract_status)
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)

    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client)
    ).where(Contract.tenant_id == current_user.tenant_id)
    
    if booking_id is not None:
        stmt = stmt.where(Contract.booking_id == booking_id)
    if contract_status is not None:
        stmt = stmt.where(Contract.status == contract_status)
        
    stmt = stmt.order_by(Contract.created_at.desc())
    result = await db.execute(stmt)
    contracts = result.scalars().unique().all()
    
    await set_cached_contract_list(current_user.tenant_id, booking_id, contract_status, contracts)
    return paginate_items(contracts, total=len(contracts), page=page, page_size=page_size)


@router.get("/{contract_id}", response_model=ContractOut)
@limiter.limit("60/minute")
async def get_contract(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await get_authorized_contract_async(contract_id, current_user, db)
    
    # Eager load for Pydantic serialization
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client)
    ).where(Contract.id == contract.id)
    result = await db.execute(stmt)
    return result.scalars().unique().first()


@router.get("/{contract_id}/pdf")
@limiter.limit("30/minute")
async def download_contract_pdf(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await get_authorized_contract_async(contract_id, current_user, db)
    
    pdf_bytes = await generate_contract_pdf(contract, db)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=contract-{contract.contract_number}.pdf"}
    )
