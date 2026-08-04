# app/routers/vault/financials.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.models.contracts import Contract, ContractStatus
from app.models.users import User
from app.schemas.invoice import InvoiceOut
from app.schemas.contract import ContractOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import invalidate_invoice_cache, invalidate_contract_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/financials", tags=["vault-financials"])

# ---------------------------------------------------------------------------
# INVOICES
# ---------------------------------------------------------------------------

@router.get("/invoices", response_model=PaginatedResponse[InvoiceOut])
@limiter.limit("60/minute")
async def list_vault_invoices(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch invoices that are voided
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client)
    ).where(
        Invoice.tenant_id == current_user.tenant_id,
        Invoice.status == InvoiceStatus.void
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            Invoice.invoice_number.ilike(search_lower)
        )
        
    stmt = stmt.order_by(Invoice.updated_at.desc())
    
    result = await db.execute(stmt)
    invoices = result.scalars().unique().all()
    return paginate_items(invoices, total=len(invoices), page=page, page_size=page_size)

@router.post("/invoices/{invoice_id}/restore", response_model=InvoiceOut)
@limiter.limit("10/minute")
async def restore_vault_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found in vault")
        
    # Restore logic: Flip status back to draft
    invoice.status = InvoiceStatus.draft
    
    await db.commit()
    await db.refresh(invoice)

    # ✅ Invalidate invoice cache so it appears in active lists
    await invalidate_invoice_cache(current_user.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_invoice", target_type="invoice", target_id=invoice.id,
        details={"invoice_number": invoice.invoice_number}
    )
    await db.commit()  # Commit the activity log flush

    return invoice

@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found in vault")
        
    # Capture details before permanent deletion
    invoice_number = invoice.invoice_number
        
    await db.delete(invoice)
    await db.commit()

    # ✅ Invalidate invoice cache
    await invalidate_invoice_cache(current_user.tenant_id)
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_invoice", target_type="invoice", target_id=invoice_id,
        details={"invoice_number": invoice_number}
    )
    await db.commit()  # Commit the activity log flush

# ---------------------------------------------------------------------------
# CONTRACTS
# ---------------------------------------------------------------------------

@router.get("/contracts", response_model=PaginatedResponse[ContractOut])
@limiter.limit("60/minute")
async def list_vault_contracts(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch contracts that are voided
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client)
    ).where(
        Contract.tenant_id == current_user.tenant_id,
        Contract.status == ContractStatus.void
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            Contract.contract_number.ilike(search_lower)
        )
        
    stmt = stmt.order_by(Contract.updated_at.desc())
    
    result = await db.execute(stmt)
    contracts = result.scalars().unique().all()
    return paginate_items(contracts, total=len(contracts), page=page, page_size=page_size)

@router.post("/contracts/{contract_id}/restore", response_model=ContractOut)
@limiter.limit("10/minute")
async def restore_vault_contract(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Contract).where(
        Contract.id == contract_id,
        Contract.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found in vault")
        
    # Restore logic: Flip status back to draft
    contract.status = ContractStatus.draft
    
    await db.commit()
    await db.refresh(contract)

    # ✅ Invalidate contract cache so it appears in active lists
    await invalidate_contract_cache(current_user.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_contract", target_type="contract", target_id=contract.id,
        details={"contract_number": contract.contract_number}
    )
    await db.commit()  # Commit the activity log flush

    return contract

@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_contract(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Contract).where(
        Contract.id == contract_id,
        Contract.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found in vault")
        
    # Capture details before permanent deletion
    contract_number = contract.contract_number
        
    await db.delete(contract)
    await db.commit()

    # ✅ Invalidate contract cache
    await invalidate_contract_cache(current_user.tenant_id)
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_contract", target_type="contract", target_id=contract_id,
        details={"contract_number": contract_number}
    )
    await db.commit()  # Commit the activity log flush
