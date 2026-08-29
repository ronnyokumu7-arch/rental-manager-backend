from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.subscription import require_active_subscription
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.users import User
from app.schemas.payment import PaymentOut, PaymentVoid
from app.services.cache import invalidate_payment_cache, invalidate_subscription_cache
from ._helpers import get_authorized_payment_async

# ✅ NEW: Import Activity Loggers
from app.services.activity_logs.payment import PaymentActivityLogger

router = APIRouter()


@router.post("/{payment_id}/void", response_model=PaymentOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Financial action
async def void_payment(
    request: Request,
    payment_id: int,
    payload: PaymentVoid,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """
    Void a completed payment and adjust the linked invoice balance.
    """
    payment = await get_authorized_payment_async(payment_id, current_user, db)

    if payment.status == PaymentStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment is already void"
        )
    if payment.status != PaymentStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed payments can be voided"
        )

    # ✅ Defense in depth: verify invoice belongs to tenant
    invoice_stmt = select(Invoice).where(
        Invoice.id == payment.invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    invoice_result = await db.execute(invoice_stmt)
    invoice = invoice_result.scalars().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked invoice not found"
        )

    # Recalculate invoice balance
    original_paid = invoice.amount_paid or Decimal("0")
    new_paid = max(Decimal("0"), original_paid - payment.amount)
    invoice.amount_paid = new_paid

    # Update invoice status based on new balance
    amount_due = invoice.amount_due or Decimal("0")
    if invoice.status == InvoiceStatus.paid and new_paid < amount_due:
        invoice.status = InvoiceStatus.partially_paid
    elif new_paid <= Decimal("0"):
        invoice.status = InvoiceStatus.sent

    payment.status = PaymentStatus.void
    payment.notes = f"VOIDED by admin {current_user.id}: {payload.reason}"

    await db.commit()
    await db.refresh(payment)
    
    # ✅ CRITICAL: Invalidate both payment and subscription caches
    # Voiding a payment reduces invoice.amount_paid, which could affect subscription warnings
    await invalidate_payment_cache(current_user.tenant_id)
    await invalidate_subscription_cache(current_user.tenant_id)
    
    # ✅ NEW: Log the payment void
    try:
        await PaymentActivityLogger.on_voided(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            payment=payment,
            reason=payload.reason,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log payment void: {e}")
    
    return payment
