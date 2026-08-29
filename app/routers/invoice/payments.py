from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.users import User
from app.schemas.payment import PaymentCreate, PaymentOut
from app.services.cache import invalidate_subscription_cache, invalidate_invoice_cache
from app.services.activity_logs.payment import PaymentActivityLogger  # ✅ NEW

router = APIRouter()


@router.post("/{invoice_id}/record-payment", response_model=PaymentOut)
@limiter.limit("30/minute")  # 🚨 STRICT: Direct financial transaction and state change
async def record_offline_payment(
    request: Request,
    invoice_id: int,
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # ✅ Validate payment amount is positive (defense in depth)
    if payload.amount <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment amount must be greater than zero"
        )

    # ✅ Async query to fetch the invoice with tenant isolation
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    invoice = (await db.execute(stmt)).scalars().first()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot record payment against a void invoice"
        )
    
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already fully paid"
        )

    remaining = (invoice.amount_due or Decimal("0")) - (invoice.amount_paid or Decimal("0"))
    if payload.amount > remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount exceeds remaining balance of {remaining} {invoice.currency_code}"
        )

    now = datetime.now(timezone.utc)

    db_payment = Payment(
        invoice_id=invoice.id,
        tenant_id=current_user.tenant_id,
        amount=payload.amount,
        currency_code=payload.currency_code,
        method=payload.method,
        reference=payload.reference,
        status=PaymentStatus.completed,
        paid_at=now,
        recorded_by=current_user.id,
        notes=payload.notes,
    )
    db.add(db_payment)

    new_paid = (invoice.amount_paid or Decimal("0")) + payload.amount
    invoice.amount_paid = new_paid

    if new_paid >= (invoice.amount_due or Decimal("0")):
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now
    elif new_paid > Decimal("0"):
        invoice.status = InvoiceStatus.partially_paid

    # ✅ Async commit and refresh
    await db.commit()
    await db.refresh(db_payment)
    
    # ✅ CRITICAL: Invalidate caches since payment status changed
    # This ensures subscription warnings and invoice lists update immediately
    await invalidate_subscription_cache(current_user.tenant_id)
    await invalidate_invoice_cache(current_user.tenant_id)
    
    # ✅ NEW: Log the payment received
    try:
        await PaymentActivityLogger.on_recorded(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            payment=db_payment,
            invoice_number=invoice.invoice_number,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log payment received: {e}")
    
    return db_payment
