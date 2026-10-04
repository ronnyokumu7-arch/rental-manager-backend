# app/routers/invoice/payments.py
"""
✅ OFFLINE PAYMENT RECORDING — operator-logged payments (M-Pesa/cash/bank).

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT: balance/amount guards return field_errors so the payment form
   highlights the exact problem (zero / over-balance).
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload  # ✅ NEW: Added import

from app.core.errors import BadRequestError, NotFoundError, ValidationFailedError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking  # ✅ NEW: Added import
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
        raise ValidationFailedError(
            title="Invalid Amount",
            message="Payment amount must be greater than zero.",
            field_errors={"amount": "Must be greater than zero"},
        )

    # ✅ Async query to fetch the invoice with tenant isolation
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    invoice = (await db.execute(stmt)).scalars().first()

    if not invoice:
        raise NotFoundError(
            title="Invoice Not Found",
            message="We couldn't find this invoice, or you may not have access to it.",
        )
    
    if invoice.status == InvoiceStatus.void:
        raise BadRequestError(
            title="Void Invoice",
            message="Cannot record a payment against a void invoice.",
        )
    
    if invoice.status == InvoiceStatus.paid:
        raise BadRequestError(
            title="Already Fully Paid",
            message="This invoice is already fully paid.",
        )

    remaining = (invoice.amount_due or Decimal("0")) - (invoice.amount_paid or Decimal("0"))
    if payload.amount > remaining:
        raise ValidationFailedError(
            title="Amount Exceeds Balance",
            message=f"The remaining balance is {remaining} {invoice.currency_code}. Record that amount or less.",
            field_errors={"amount": f"Maximum {remaining} {invoice.currency_code}"},
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

    # ✅ NEW: Re-fetch payment with eager-loaded client chain (prevents MissingGreenlet)
    stmt = select(Payment).options(
        selectinload(Payment.invoice)
        .selectinload(Invoice.booking)
        .selectinload(Booking.client)
    ).where(Payment.id == db_payment.id)
    result = await db.execute(stmt)
    db_payment = result.scalars().unique().first()
    
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
