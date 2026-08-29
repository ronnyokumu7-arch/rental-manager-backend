from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
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
    invalidate_invoice_cache, invalidate_subscription_cache, invalidate_booking_cache,
)
from app.services.invoice_pdf import generate_invoice_pdf
from app.services.pricing_selfdrive import quote_selfdrive  # ✅ PHASE 1: pure engine

router = APIRouter()


class ReschedulePayload(BaseModel):
    """Client proposes a new schedule; re-prices and requires re-accept."""
    pickup_at: datetime
    scheduled_return_at: datetime

    @property
    def valid(self) -> bool:
        return self.scheduled_return_at > self.pickup_at


async def _load_invoice_by_token(db: AsyncSession, token: str) -> Invoice:
    stmt = select(Invoice).where(Invoice.share_token == token)
    invoice = (await db.execute(stmt)).scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This link has expired")
    return invoice


async def _load_booking_locked(db: AsyncSession, booking_id: int) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
    booking = (await db.execute(stmt)).scalars().first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


async def _build_public_view(db: AsyncSession, invoice_id: int) -> PublicInvoiceView:
    """✅ Single source of truth for the public invoice JSON shape."""
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
        selectinload(Invoice.booking).selectinload(Booking.driver),
        selectinload(Invoice.tenant).selectinload(Tenant.profile)
    ).where(Invoice.id == invoice_id)

    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()

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
            bank_account_number=bank_config.account_number if bank_config else None,
            bank_account_name=bank_config.account_name if bank_config else None,
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
        remaining_balance=max(0, (invoice.amount_due or 0) - (invoice.amount_paid or 0)),
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
        raise HTTPException(status_code=400, detail="This quotation has been voided")
    if invoice.doc_type != "quotation":
        raise HTTPException(status_code=400, detail="This invoice has already been accepted")

    booking = await _load_booking_locked(db, invoice.booking_id)
    if booking.status in (BookingStatus.cancelled, BookingStatus.completed):
        raise HTTPException(status_code=400, detail="This booking can no longer be accepted")

    # Morph + contract + confirm (all flush-only), then ONE commit.
    await morph_quotation_to_invoice(booking, db)
    contract = await ensure_contract_for_booking(booking, db)
    await BookingLifecycleService.confirm_client(db, booking)

    await db.commit()

    # Background: render contract PDF + auto-send (wire to notification service).
    background_tasks.add_task(render_and_store_contract_pdf, contract.id)

    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_invoice_cache(booking.tenant_id)

    return await _build_public_view(db, invoice.id)


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
        return await _build_public_view(db, invoice.id)   # idempotent
    if booking.status == BookingStatus.completed:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed booking")

    await BookingLifecycleService.cancel_client(db, booking, CancellationReason.client_cancelled)
    if invoice.status != InvoiceStatus.void:
        invoice.status = InvoiceStatus.void   # void the transaction; payments stay as records

    await db.commit()
    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_invoice_cache(booking.tenant_id)

    return await _build_public_view(db, invoice.id)


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
        raise HTTPException(status_code=422, detail="Return must be after pickup")

    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=400, detail="This booking has been voided")

    booking = await _load_booking_locked(db, invoice.booking_id)
    if booking.status == BookingStatus.active:
        raise HTTPException(status_code=400, detail="Cannot reschedule an active trip")
    if booking.status == BookingStatus.cancelled:
        raise HTTPException(status_code=400, detail="Cannot reschedule a cancelled booking")

    # Apply new schedule
    booking.pickup_at = payload.pickup_at
    booking.scheduled_return_at = payload.scheduled_return_at
    booking.start_date = payload.pickup_at
    booking.end_date = payload.scheduled_return_at

    # ✅ PHASE 1: Re-price server-side via the pure self-drive engine
    rate = Decimal(booking.daily_rate or 0)
    if rate <= 0:
        raise HTTPException(status_code=422, detail="Booking has no daily rate configured")

    try:
        # Driver fee via explicit query (never lazy-load in async context)
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
        raise HTTPException(status_code=422, detail="Invalid schedule")

    # New terms → engine truth (operator can re-adjust via invoice afterwards)
    booking.billable_days = quote.billable_days
    booking.computed_total = quote.total
    booking.total_amount = quote.total
    booking.manually_adjusted = False
    booking.price_note = None

    # Back to quotation + pending → client must re-accept the new terms
    invoice.doc_type = "quotation"
    invoice.amount_due = booking.total_amount
    invoice.due_date = payload.pickup_at
    if booking.status == BookingStatus.confirmed:
        booking.status = BookingStatus.pending

    await db.commit()
    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_invoice_cache(booking.tenant_id)

    return await _build_public_view(db, invoice.id)


# =============================================================================
# EXISTING: view / pay / pdf (unchanged)
# =============================================================================
@router.get("/public/{token}", response_model=PublicInvoiceView)
@limiter.limit("30/minute")
async def view_invoice_public(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=400, detail="This invoice has been voided")
    return await _build_public_view(db, invoice.id)


@router.post("/public/{token}/pay", response_model=PublicInvoiceView)
@limiter.limit("10/minute")
async def record_payment_public(
    request: Request, token: str, payload: PublicPaymentCreate, db: AsyncSession = Depends(get_db)
):
    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=400, detail="Cannot record payment against a void invoice")
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(status_code=400, detail="Invoice is already fully paid")

    remaining = (invoice.amount_due or Decimal("0")) - (invoice.amount_paid or Decimal("0"))
    if payload.amount > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"Amount exceeds remaining balance of {remaining} {invoice.currency_code}",
        )

    now = datetime.now(timezone.utc)
    db_payment = Payment(
        invoice_id=invoice.id, tenant_id=invoice.tenant_id, amount=payload.amount,
        currency_code=invoice.currency_code, method=payload.method, reference=payload.reference,
        status=PaymentStatus.completed, paid_at=now, recorded_by=None,
        notes=payload.notes or "Self-reported by client via public payment portal",
    )
    db.add(db_payment)

    new_paid = (invoice.amount_paid or Decimal("0")) + payload.amount
    invoice.amount_paid = new_paid
    if new_paid >= (invoice.amount_due or Decimal("0")):
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now
    elif new_paid > Decimal("0"):
        invoice.status = InvoiceStatus.partially_paid

    await db.commit()
    await db.refresh(db_payment)
    await invalidate_subscription_cache(invoice.tenant_id)
    await invalidate_invoice_cache(invoice.tenant_id)

    return await _build_public_view(db, invoice.id)


@router.get("/public/{token}/pdf")
@limiter.limit("15/minute")
async def download_invoice_pdf_public(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    invoice = await _load_invoice_by_token(db, token)
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=400, detail="This invoice has been voided")
    pdf_bytes = await generate_invoice_pdf(invoice, db)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{invoice.invoice_number}.pdf"},
    )
