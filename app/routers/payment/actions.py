"""
✅ PAYMENT ACTIONS — void with invoice balance recalculation.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B): payments on VOID invoices are frozen as records
   (matches the cancel flow's "payments stay as records" rule).
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AuthorizationError, BadRequestError, NotFoundError, ValidationFailedError
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.users import User
from app.schemas.payment import PaymentOut, PaymentVoid
from app.services.cache import (
    invalidate_invoice_cache,
    invalidate_payment_cache,
    invalidate_subscription_cache,
)
from ._helpers import get_authorized_payment_async

# ✅ NEW: Import Activity Loggers
from app.services.activity_logs.payment import PaymentActivityLogger

router = APIRouter()


@router.post("/{payment_id}/confirm", response_model=PaymentOut)
@limiter.limit("10/minute")
async def confirm_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Confirm a client-reported payment and apply it to the tenant's invoice."""
    tenant_id = current_user.tenant_id
    if tenant_id is None:
        raise AuthorizationError(
            title="No Agency Linked",
            message="Your account isn't linked to an agency, so it can't confirm invoice payments.",
        )

    payment_stmt = (
        select(Payment)
        .where(
            Payment.id == payment_id,
            Payment.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    payment = (await db.execute(payment_stmt)).scalars().first()
    if payment is None:
        raise NotFoundError(
            title="Payment Not Found",
            message="We couldn't find this payment, or you may not have access to it.",
        )
    if payment.status != PaymentStatus.pending:
        raise BadRequestError(
            title="Payment Is Not Awaiting Confirmation",
            message="Only pending payment reports can be confirmed.",
        )

    invoice_stmt = (
        select(Invoice)
        .where(
            Invoice.id == payment.invoice_id,
            Invoice.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    invoice = (await db.execute(invoice_stmt)).scalars().first()
    if invoice is None:
        raise NotFoundError(
            title="Linked Invoice Missing",
            message="The invoice linked to this payment couldn't be found.",
        )
    if invoice.status == InvoiceStatus.void:
        raise BadRequestError(
            title="Invoice Is Void",
            message="A payment report for a void invoice can't be confirmed.",
        )

    remaining = (invoice.amount_due or Decimal("0")) - (invoice.amount_paid or Decimal("0"))
    if payment.amount > remaining:
        raise ValidationFailedError(
            title="Payment Exceeds Balance",
            message=f"The remaining balance is {remaining} {invoice.currency_code}. This payment can't be confirmed.",
            field_errors={"amount": f"Maximum {remaining} {invoice.currency_code}"},
        )

    now = datetime.now(timezone.utc)
    new_paid = (invoice.amount_paid or Decimal("0")) + payment.amount
    payment.status = PaymentStatus.completed
    payment.paid_at = now
    payment.recorded_by = current_user.id
    invoice.amount_paid = new_paid
    if new_paid >= (invoice.amount_due or Decimal("0")):
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now
    elif new_paid > Decimal("0"):
        invoice.status = InvoiceStatus.partially_paid

    invoice_number = invoice.invoice_number
    await db.commit()
    await db.refresh(payment)
    await invalidate_payment_cache(tenant_id)
    await invalidate_invoice_cache(tenant_id)
    await invalidate_subscription_cache(tenant_id)

    try:
        logged_payment_stmt = select(Payment).options(
            selectinload(Payment.invoice)
            .selectinload(Invoice.booking)
            .selectinload(Booking.client)
        ).where(
            Payment.id == payment_id,
            Payment.tenant_id == tenant_id,
        )
        logged_payment = (await db.execute(logged_payment_stmt)).scalars().unique().first()
        if logged_payment is None:
            raise RuntimeError("Confirmed payment could not be reloaded for activity logging")
        await PaymentActivityLogger.on_recorded(
            db=db,
            tenant_id=tenant_id,
            user_id=current_user.id,
            payment=logged_payment,
            invoice_number=invoice_number,
        )
        await db.commit()
        return logged_payment
    except Exception as e:
        await db.rollback()
        print(f"⚠️ Warning: Failed to log confirmed payment: {e}")
        return payment


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
    payment = await get_authorized_payment_async(
        payment_id,
        current_user,
        db,
        for_update=True,
    )

    if payment.status == PaymentStatus.void:
        raise BadRequestError(
            title="Already Void",
            message="This payment is already void.",
        )
    if payment.status != PaymentStatus.completed:
        raise BadRequestError(
            title="Only Completed Payments Can Be Voided",
            message="Pending or failed payments can't be voided.",
        )

    # ✅ Defense in depth: verify invoice belongs to tenant
    invoice_stmt = select(Invoice).where(
        Invoice.id == payment.invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).with_for_update()
    invoice_result = await db.execute(invoice_stmt)
    invoice = invoice_result.scalars().first()
    
    if not invoice:
        raise NotFoundError(
            title="Linked Invoice Missing",
            message="The invoice linked to this payment couldn't be found. Contact support for help.",
        )

    # ✅ Phase B: void invoices freeze their payment records (cancel-flow rule)
    if invoice.status == InvoiceStatus.void:
        raise BadRequestError(
            title="Invoice Is Void",
            message="This payment belongs to a void invoice. Void-invoice payments stay as records and can't be voided.",
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
