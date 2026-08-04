# app/routers/vault/payments.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.payments import Payment, PaymentStatus
from app.models.invoices import Invoice
from app.models.bookings import Booking
from app.models.users import User
from app.schemas.payment import PaymentOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import invalidate_payment_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/payments", tags=["vault-payments"])

@router.get("/", response_model=PaginatedResponse[PaymentOut])
@limiter.limit("60/minute")
async def list_vault_payments(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch payments that are completed (history) OR voided/refunded (graveyard)
    stmt = select(Payment).options(
        selectinload(Payment.invoice)
        .selectinload(Invoice.booking)
        .selectinload(Booking.client)
    ).where(
        Payment.tenant_id == current_user.tenant_id,
        or_(
            Payment.status == PaymentStatus.completed,
            Payment.status.in_([PaymentStatus.void, PaymentStatus.refunded])
        )
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        # Search by reference code or notes (invoice number is handled by the computed field, 
        # but we can't easily search it here without a join, so we stick to payment fields)
        stmt = stmt.where(
            Payment.reference.ilike(search_lower) |
            Payment.notes.ilike(search_lower)
        )
        
    # Sort by most recently paid/updated first
    stmt = stmt.order_by(Payment.paid_at.desc().nullslast(), Payment.created_at.desc())
    
    result = await db.execute(stmt)
    payments = result.scalars().unique().all()
    return paginate_items(payments, total=len(payments), page=page, page_size=page_size)

@router.post("/{payment_id}/restore", response_model=PaymentOut)
@limiter.limit("10/minute")
async def restore_vault_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Payment).where(
        Payment.id == payment_id,
        Payment.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    payment = result.scalars().first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found in vault")
        
    # Restore logic: Flip status back to completed (or pending if it was voided before completion)
    if payment.status in [PaymentStatus.void, PaymentStatus.refunded]:
        payment.status = PaymentStatus.completed
        
    await db.commit()
    await db.refresh(payment)

    # ✅ Invalidate payment cache so it appears in active lists
    await invalidate_payment_cache(current_user.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_payment", target_type="payment", target_id=payment.id,
        details={"reference": payment.reference, "amount": str(payment.amount)}
    )
    await db.commit()  # Commit the activity log flush

    return payment

@router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Payment).where(
        Payment.id == payment_id,
        Payment.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    payment = result.scalars().first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found in vault")
        
    # Capture details before permanent deletion
    payment_reference = payment.reference
    payment_amount = str(payment.amount)
        
    # Hard delete: Permanent destruction from the database
    await db.delete(payment)
    await db.commit()

    # ✅ Invalidate payment cache
    await invalidate_payment_cache(current_user.tenant_id)
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_payment", target_type="payment", target_id=payment_id,
        details={"reference": payment_reference, "amount": payment_amount}
    )
    await db.commit()  # Commit the activity log flush
