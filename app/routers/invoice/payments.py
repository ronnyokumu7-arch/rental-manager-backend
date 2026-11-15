"""
✅ OFFLINE PAYMENT RECORDING — operator-logged payments (M-Pesa/cash/bank).

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT: balance/amount guards return field_errors so the payment form
   highlights the exact problem (zero / over-balance).
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import BadRequestError, NotFoundError, ValidationFailedError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.users import User
from app.schemas.payment import PaymentCreate, PaymentOut
# ✅ FIX 1: Added invalidate_payment_cache to imports
from app.services.cache import invalidate_subscription_cache, invalidate_invoice_cache, invalidate_payment_cache
from app.services.activity_logs.payment import PaymentActivityLogger

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{invoice_id}/record-payment", response_model=PaymentOut)
@limiter.limit("30/minute")
async def record_offline_payment(
    request: Request,
    invoice_id: int,
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    if payload.amount <= Decimal("0"):
        raise ValidationFailedError(
            title="Invalid Amount",
            message="Payment amount must be greater than zero.",
            field_errors={"amount": "Must be greater than zero"},
        )

    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).with_for_update()
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

    # ✅ FIX 2: Commit the financial transaction FIRST. 
    # A failed activity log must NEVER rollback a successful payment.
    await db.commit()
    await db.refresh(db_payment)

    # ✅ FIX 3: Invalidate ALL relevant caches immediately
    await invalidate_invoice_cache(current_user.tenant_id)
    await invalidate_payment_cache(current_user.tenant_id)  # ✅ ADDED
    
    # ✅ FIX 4: Log the payment received (non-blocking, non-transactional)
    try:
        await PaymentActivityLogger.on_recorded(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            payment=db_payment,
            invoice_number=invoice.invoice_number,
        )
        # If the logger does its own db.add(), we can commit it here safely 
        # without affecting the already-committed payment.
        await db.commit()
    except Exception as e:
        # ✅ CRITICAL: Do NOT rollback the payment if logging fails.
        logger.error(f"⚠️ Failed to log payment received for invoice {invoice.id}: {e}")
    
    # Re-fetch payment with eager-loaded client chain for the response
    stmt = select(Payment).options(
        selectinload(Payment.invoice)
        .selectinload(Invoice.booking)
        .selectinload(Booking.client)
    ).where(Payment.id == db_payment.id)
    result = await db.execute(stmt)
    final_payment = result.scalars().unique().first()
    
    return final_payment

@router.get("/{payment_id}", response_model=PaymentOut)
@limiter.limit("60/minute")
async def get_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single payment lookup. Not cached. Enforces tenant isolation."""
    stmt = select(Payment).options(
        selectinload(Payment.invoice)
        .selectinload(Invoice.booking)
        .selectinload(Booking.client)
    ).where(
        Payment.id == payment_id,
        Payment.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    payment = result.scalars().unique().first()

    if not payment:
        raise NotFoundError(
            title="Payment Not Found",
            message="We couldn't find this payment, or you may not have access to it.",
        )

    return payment
