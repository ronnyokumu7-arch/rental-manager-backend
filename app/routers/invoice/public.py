"""
✅ PUBLIC INVOICE/QUOTATION PAGE — view / accept / cancel / reschedule / pay / pdf.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ COPY RULE: this is client-facing — messages speak to the client and point
   them at the agency ("contact the agency"), never at dashboard concepts.
✅ AUDIT (Phase B): PDF failures → typed ServerError (was raw 500).
✅ AUDIT (Phase C): payment submission no longer blocked by notification wiring.
   The "payment proof submitted" notification is fired in an ISOLATED background
   session (system RLS context) AFTER the payment commits, so a notification
   failure can never poison the payment transaction.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    AppException,
    BadRequestError,
    GoneError,
    NotFoundError,
    ServerError,
    ValidationFailedError,
    navigate_action,
)
from app.core.limiter import limiter
from app.db.database import (
    get_db,
    set_public_rls_context,
    set_rls_context,
    AsyncSessionLocal,
    set_system_rls_context,
)
from app.models.bookings import Booking, BookingStatus, CancellationReason
from app.models.drivers import Driver
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle
from app.models.payment_gateways.mpesa import MpesaConfig
from app.models.payment_gateways.bank import BankAccountConfig
from app.models.payment_gateways.airtel import AirtelMoneyConfig
from app.schemas.invoice import PublicInvoiceView, PublicPaymentDetails, PublicPaymentCreate
from app.services.booking_lifecycle import BookingLifecycleService
from app.services.contracts import ensure_contract_for_booking, render_and_store_contract_pdf
from app.services.invoices import morph_quotation_to_invoice
from app.services.cache import (
    invalidate_invoice_cache, invalidate_payment_cache,
    invalidate_booking_cache, invalidate_contract_cache,
)
from app.services.invoice_pdf import generate_invoice_pdf
from app.services.pricing_selfdrive import quote_selfdrive
from app.services.notification_triggers import NotificationTriggers

router = APIRouter()

logger = logging.getLogger(__name__)

_PUBLIC_HOME = navigate_action("Go Home", "/")

MAX_SIGNATURE_BYTES = 1_000_000  # (kept for parity with contract flow; unused here)


class ReschedulePayload(BaseModel):
    """Client proposes a new schedule; re-prices and requires re-accept."""
    pickup_at: datetime
    scheduled_return_at: datetime

    @property
    def valid(self) -> bool:
        return self.scheduled_return_at > self.pickup_at


def _voided_doc_error(doc_word: str = "invoice") -> BadRequestError:
    return BadRequestError(
        title="No Longer Valid",
        message=f"This {doc_word} was cancelled by the agency. Contact them if you believe this is a mistake.",
        action=_PUBLIC_HOME,
    )


async def _load_invoice_by_token(db: AsyncSession, token: str) -> Invoice:
    await set_public_rls_context(db, token)
    stmt = select(Invoice).where(Invoice.share_token == token)
    invoice = (await db.execute(stmt)).scalars().first()
    if not invoice:
        raise NotFoundError(
            title="Link Not Recognized",
            message="We couldn't find this invoice. Check that the link is complete and try again.",
            action=_PUBLIC_HOME,
        )
    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise GoneError(
            title="Link Expired",
            message="This link has expired. Ask the agency to send you a new one.",
            action=_PUBLIC_HOME,
        )
    await set_rls_context(db, tenant_id=invoice.tenant_id)
    return invoice


async def _load_booking_locked(db: AsyncSession, booking_id: int) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
    booking = (await db.execute(stmt)).scalars().first()
    if not booking:
        raise NotFoundError(
            title="Booking Not Found",
            message="We couldn't find this booking. Contact the agency for help.",
            action=_PUBLIC_HOME,
        )
    return booking


async def _notify_payment_submitted_bg(
    payment_id: int,
    tenant_id: int,
    target_user_id: int,
    amount: float,
    reference: str,
) -> None:
    """
    ✅ Fire the 'payment proof submitted' notification in an ISOLATED session
    with SYSTEM RLS context (mirrors render_and_store_contract_pdf).

    Runs AFTER the payment commits, so a notification/RLS failure can never
    poison the payment transaction. Best-effort: failures are logged, not raised.
    """
    try:
        async with AsyncSessionLocal() as db:
            await set_system_rls_context(db)
            await NotificationTriggers.on_payment_submitted(
                db=db,
                tenant_id=tenant_id,
                target_user_id=target_user_id,
                amount=amount,
                reference=reference,
                payment_id=payment_id,
            )
            await db.commit()
    except Exception:
        logger.exception(
            f"Failed to notify payment submission for payment {payment_id} (tenant {tenant_id})"
        )


async def _build_public_view(
    db: AsyncSession, invoice_id: int, token: str | None = None
) -> PublicInvoiceView:
    """✅ Single source of truth for the public invoice JSON shape."""
    if token is not None:
        await set_public_rls_context(db, token)
        token_invoice = (await db.execute(
            select(Invoice).where(Invoice.share_token == token)
        )).scalars().first()
        if not token_invoice or token_invoice.id != invoice_id:
            raise NotFoundError(
                title="Link Not Recognized",
                message="We couldn't find this invoice. Check that the link is complete and try again.",
                action=_PUBLIC_HOME,
            )
        await set_rls_context(db, tenant_id=token_invoice.tenant_id)

    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
        selectinload(Invoice.booking).selectinload(Booking.driver),
        selectinload(Invoice.tenant).selectinload(Tenant.profile)
    ).where(Invoice.id == invoice_id)

    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()

    # ✅ NEW: Fetch the actual pending payment amount (there's at most 1 due to the strict lock)
    pending_payment_amount = await db.scalar(
        select(Payment.amount).where(
            Payment.invoice_id == invoice.id,
            Payment.tenant_id == invoice.tenant_id,
            Payment.status == PaymentStatus.pending,
        )
    )
    pending_amount = pending_payment_amount or Decimal("0")

    booking = invoice.booking
    client = booking.client if booking else None
    vehicle = booking.vehicle if booking else None
    driver = booking.driver if booking else None
    tenant = invoice.tenant
    profile = tenant.profile if tenant else None

    payment_details = None
    mpesa_config = (await db.execute(select(MpesaConfig).where(
        MpesaConfig.tenant_id == tenant.id, MpesaConfig.is_active == True))).scalars().first()
    bank_config = (await db.execute(select(BankAccountConfig).where(
        BankAccountConfig.tenant_id == tenant.id, BankAccountConfig.is_primary == True))).scalars().first()
    airtel_config = (await db.execute(select(AirtelMoneyConfig).where(
        AirtelMoneyConfig.tenant_id == tenant.id, AirtelMoneyConfig.is_active == True))).scalars().first()

    if mpesa_config or bank_config or airtel_config:
        payment_details = PublicPaymentDetails(
            method_type=mpesa_config.method_type if mpesa_config else None,
            business_shortcode=mpesa_config.business_shortcode if mpesa_config else None,
            till_number=mpesa_config.till_number if mpesa_config else None,
            account_number=mpesa_config.account_number if mpesa_config else None,
            account_name=mpesa_config.account_name if mpesa_config else None,
            airtel_number=airtel_config.phone_number if airtel_config else None,
            bank_name=bank_config.bank_name if bank_config else None,
            bank_account_number=bank_config.bank_account_number if bank_config else None,
            bank_account_name=bank_config.bank_account_name if bank_config else None,
            branch_code=bank_config.branch_code if bank_config else None,
            swift_code=bank_config.swift_code if bank_config else None,
            currency=bank_config.currency if bank_config else None,
            tenant_phone=profile.phone if profile else None,
        )

    return PublicInvoiceView(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        doc_type=invoice.doc_type,
        amount_due=invoice.amount_due,
        amount_paid=invoice.amount_paid or 0,
        remaining_balance=max(Decimal("0"), (invoice.amount_due or 0) - (invoice.amount_paid or 0)),
        pending_amount=pending_amount,  # ✅ NEW FIELD
        payment_reported=pending_amount > 0,  # ✅ UPDATED: derived from actual amount
        currency_code=invoice.currency_code,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        created_at=invoice.created_at,
        discount_amount=invoice.discount_amount or 0,
        discount_reason=invoice.discount_reason,
        client_name=client.full_name if client else "Valued Client",
        client_phone=client.phone if client else None,
        tenant_name=tenant.name if tenant else "Unknown Agency",
        tenant_logo_url=profile.logo_url if profile else None,
        tenant_email=profile.email if profile else None,
        tenant_phone=profile.phone if profile else None,
        vehicle_description=f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})" if vehicle else "N/A",
        vehicle_name=f"{vehicle.make} {vehicle.model}" if vehicle else None,
        vehicle_plate=vehicle.plate_number if vehicle else None,
        booking_start_date=str(booking.start_date) if booking else None,
        booking_end_date=str(booking.end_date) if booking else None,
        driver_name=driver.full_name if driver else None,
        driver_phone=driver.phone if driver else None,
        driver_dl_number=driver.dl_number if driver else None,
        payment_details=payment_details,
    )


# =============================================================================
# ✅ LIFECYCLE: client actions on the morphing quotation/invoice page
# =============================================================================
@router.post("/public/{token}/accept", response_model=PublicInvoiceView)
@limiter.limit("10/minute")
async def accept_quotation_public(
    request: Request,
    token: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    ✅ Client accepts the quotation:
      quotation→invoice (due=rental start) + booking pending→confirmed +
      auto-contract (+ background PDF). ONE atomic commit.
    """
    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise _voided_doc_error("quotation")
    if invoice.doc_type != "quotation":
        raise BadRequestError(
            title="Already Accepted",
            message="This quotation has already been accepted. Your invoice and payment options are shown on this page.",
        )

    booking = await _load_booking_locked(db, invoice.booking_id)
    if booking.status in (BookingStatus.cancelled, BookingStatus.completed):
        raise BadRequestError(
            title="No Longer Available",
            message="This booking can no longer be accepted. Contact the agency for help.",
            action=_PUBLIC_HOME,
        )

    await morph_quotation_to_invoice(booking, db)
    contract = await ensure_contract_for_booking(booking, db)
    await BookingLifecycleService.confirm_client(db, booking)

    await db.commit()

    background_tasks.add_task(render_and_store_contract_pdf, contract.id)

    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_invoice_cache(booking.tenant_id)
    await invalidate_contract_cache(booking.tenant_id)

    return await _build_public_view(db, invoice.id, token)


@router.post("/public/{token}/cancel", response_model=PublicInvoiceView)
@limiter.limit("10/minute")
async def cancel_booking_public(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """✅ Client cancels: booking→cancelled (reason=client_cancelled) + invoice void."""
    invoice = await _load_invoice_by_token(db, token)
    booking = await _load_booking_locked(db, invoice.booking_id)

    if booking.status == BookingStatus.cancelled:
        return await _build_public_view(db, invoice.id, token)   # idempotent
    if booking.status == BookingStatus.completed:
        raise BadRequestError(
            title="Trip Already Completed",
            message="Completed bookings can't be cancelled online. Contact the agency for help.",
            action=_PUBLIC_HOME,
        )

    await BookingLifecycleService.cancel_client(db, booking, CancellationReason.client_cancelled)
    if invoice.status != InvoiceStatus.void:
        invoice.status = InvoiceStatus.void

    await db.commit()
    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_invoice_cache(booking.tenant_id)

    return await _build_public_view(db, invoice.id, token)


@router.post("/public/{token}/reschedule", response_model=PublicInvoiceView)
@limiter.limit("10/minute")
async def reschedule_booking_public(
    request: Request,
    token: str,
    payload: ReschedulePayload,
    db: AsyncSession = Depends(get_db),
):
    """
    ✅ Client proposes a new schedule. Re-prices server-side and puts the
    document back to `quotation` + booking to `pending` → requires re-accept.
    Not allowed once the trip is active.
    """
    if not payload.valid:
        raise ValidationFailedError(
            title="Invalid Schedule",
            message="The return time must be after the pickup time.",
            field_errors={"scheduled_return_at": "Must be after the pickup time"},
        )

    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise _voided_doc_error("booking")

    booking = await _load_booking_locked(db, invoice.booking_id)
    if booking.status == BookingStatus.active:
        raise BadRequestError(
            title="Trip Already Started",
            message="Active trips can't be rescheduled online. Contact the agency to extend your booking.",
            action=_PUBLIC_HOME,
        )
    if booking.status == BookingStatus.cancelled:
        raise BadRequestError(
            title="Booking Cancelled",
            message="This booking was cancelled and can't be rescheduled. Contact the agency for help.",
            action=_PUBLIC_HOME,
        )

    booking.pickup_at = payload.pickup_at
    booking.scheduled_return_at = payload.scheduled_return_at
    booking.start_date = payload.pickup_at
    booking.end_date = payload.scheduled_return_at

    rate = Decimal(booking.daily_rate or 0)
    if rate <= 0:
        raise ValidationFailedError(
            title="Pricing Unavailable",
            message="This booking has no rate configured. Contact the agency to update your quotation.",
            action=_PUBLIC_HOME,
        )

    try:
        driver_daily_fee = None
        if booking.driver_id:
            driver = (await db.execute(
                select(Driver).where(Driver.id == booking.driver_id)
            )).scalars().first()
            if driver:
                driver_daily_fee = driver.daily_fee

        quote = quote_selfdrive(
            pickup_at=payload.pickup_at,
            return_at=payload.scheduled_return_at,
            daily_rate=rate,
            driver_daily_fee=Decimal(driver_daily_fee) if driver_daily_fee else None,
        )
    except ValueError:
        raise ValidationFailedError(
            title="Invalid Schedule",
            message="The dates you chose can't be priced. Adjust the pickup or return time and try again.",
        )

    booking.billable_days = quote.billable_days
    booking.computed_total = quote.total
    booking.total_amount = quote.total
    booking.manually_adjusted = False
    booking.price_note = None

    invoice.doc_type = "quotation"
    invoice.amount_due = booking.total_amount
    invoice.due_date = payload.pickup_at
    if booking.status == BookingStatus.confirmed:
        booking.status = BookingStatus.pending

    await db.commit()
    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_invoice_cache(booking.tenant_id)

    return await _build_public_view(db, invoice.id, token)


# =============================================================================
# EXISTING: view / pay / pdf
# =============================================================================
@router.get("/public/{token}", response_model=PublicInvoiceView)
@limiter.limit("30/minute")
async def view_invoice_public(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise _voided_doc_error()
    return await _build_public_view(db, invoice.id, token)


@router.post("/public/{token}/pay", response_model=PublicInvoiceView)
@limiter.limit("10/minute")
async def record_payment_public(
    request: Request,
    token: str,
    payload: PublicPaymentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    invoice = await _load_invoice_by_token(db, token)
    invoice_stmt = (
        select(Invoice)
        .where(
            Invoice.id == invoice.id,
            Invoice.tenant_id == invoice.tenant_id,
        )
        .with_for_update()
    )
    invoice = (await db.execute(invoice_stmt)).scalars().first()
    if invoice is None:
        raise NotFoundError(
            title="Invoice Not Found",
            message="We couldn't find this invoice. Check that the link is complete and try again.",
            action=_PUBLIC_HOME,
        )
    if invoice.status == InvoiceStatus.void:
        raise _voided_doc_error()
    if invoice.status == InvoiceStatus.paid:
        raise BadRequestError(
            title="Already Fully Paid",
            message="This invoice is fully paid. Thank you!",
        )

    # ✅ STRICT LOCK - Prevent duplicate pending payment submissions for this invoice
    existing_pending = await db.scalar(
        select(
            exists().where(
                Payment.invoice_id == invoice.id,
                Payment.status == PaymentStatus.pending,
            )
        )
    )
    if existing_pending:
        raise BadRequestError(
            title="Payment Already Reported",
            message="You have already submitted a payment proof for this invoice. Please wait for the agency to confirm it before submitting another.",
        )

    remaining = (invoice.amount_due or Decimal("0")) - (invoice.amount_paid or Decimal("0"))
    if payload.amount > remaining:
        raise ValidationFailedError(
            title="Amount Exceeds Balance",
            message=f"The remaining balance is {remaining} {invoice.currency_code}. Enter that amount or less.",
            field_errors={"amount": f"Maximum {remaining} {invoice.currency_code}"},
        )

    db_payment = Payment(
        invoice_id=invoice.id, tenant_id=invoice.tenant_id, amount=payload.amount,
        currency_code=invoice.currency_code, method=payload.method, reference=payload.reference,
        status=PaymentStatus.pending, paid_at=None, recorded_by=None,
        notes=f"Self-reported by client via public payment portal. {payload.notes or ''}".strip(),
    )
    db.add(db_payment)
    await db.flush()  # generate payment id

    # ✅ Resolve the tenant owner NOW (cheap read, inside txn) so the background
    #    notification task has the recipient without re-querying.
    tenant = await db.get(Tenant, invoice.tenant_id)
    target_user_id = tenant.owner_id if tenant else None

    # ✅ COMMIT THE PAYMENT FIRST. The notification is decoupled from this txn.
    await db.commit()
    await db.refresh(db_payment)
    await invalidate_payment_cache(invoice.tenant_id)

    # ✅ Fire the notification in an ISOLATED background session (system RLS).
    #    A notification/RLS failure here can NEVER roll back the payment.
    if target_user_id:
        background_tasks.add_task(
            _notify_payment_submitted_bg,
            payment_id=db_payment.id,
            tenant_id=invoice.tenant_id,
            target_user_id=target_user_id,
            amount=float(payload.amount),
            reference=payload.reference,
        )

    return await _build_public_view(db, invoice.id, token)


@router.get("/public/{token}/pdf")
@limiter.limit("15/minute")
async def download_invoice_pdf_public(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise _voided_doc_error()

    try:
        pdf_bytes = await generate_invoice_pdf(invoice, db)
    except (AppException,):
        raise
    except Exception:
        logger.exception(f"Public PDF generation failed for invoice {invoice.id}")
        raise ServerError(
            title="PDF Not Available Yet",
            message="We couldn't generate the PDF just now. Please try again in a moment.",
        )

    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{invoice.invoice_number}.pdf"},
    )
