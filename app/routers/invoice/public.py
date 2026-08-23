from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle
from app.models.payment_gateways.mpesa import MpesaConfig
from app.models.payment_gateways.bank import BankAccountConfig
from app.models.payment_gateways.airtel import AirtelMoneyConfig
from app.schemas.invoice import PublicInvoiceView, PublicPaymentDetails, PublicPaymentCreate
from app.services.cache import invalidate_invoice_cache, invalidate_subscription_cache
from app.services.invoice_pdf import generate_invoice_pdf

router = APIRouter()


async def _build_public_view(db: AsyncSession, invoice_id: int) -> PublicInvoiceView:
    """✅ Single source of truth for the public invoice JSON shape."""
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
        selectinload(Invoice.booking).selectinload(Booking.driver),  # ✅ MILESTONE 2
        selectinload(Invoice.tenant).selectinload(Tenant.profile)
    ).where(Invoice.id == invoice_id)

    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()

    booking = invoice.booking
    client = booking.client if booking else None
    vehicle = booking.vehicle if booking else None
    driver = booking.driver if booking else None  # ✅ MILESTONE 2
    tenant = invoice.tenant
    profile = tenant.profile if tenant else None

    # ✅ NEW: Query the gateway config tables instead of TenantProfile
    payment_details = None
    
    # Fetch M-Pesa config (if exists)
    mpesa_stmt = select(MpesaConfig).where(
        MpesaConfig.tenant_id == tenant.id,
        MpesaConfig.is_active == True
    )
    mpesa_config = (await db.execute(mpesa_stmt)).scalars().first()
    
    # Fetch Bank config (if exists, primary first)
    bank_stmt = select(BankAccountConfig).where(
        BankAccountConfig.tenant_id == tenant.id,
        BankAccountConfig.is_primary == True
    )
    bank_config = (await db.execute(bank_stmt)).scalars().first()
    
    # Fetch Airtel config (if exists)
    airtel_stmt = select(AirtelMoneyConfig).where(
        AirtelMoneyConfig.tenant_id == tenant.id,
        AirtelMoneyConfig.is_active == True
    )
    airtel_config = (await db.execute(airtel_stmt)).scalars().first()
    
    # Build payment_details from the configs
    if mpesa_config or bank_config or airtel_config:
        payment_details = PublicPaymentDetails(
            # M-Pesa fields (aligned with new model columns)
            method_type=mpesa_config.method_type if mpesa_config else None,
            business_shortcode=mpesa_config.business_shortcode if mpesa_config else None,
            till_number=mpesa_config.till_number if mpesa_config else None,
            account_number=mpesa_config.account_number if mpesa_config else None,
            account_name=mpesa_config.account_name if mpesa_config else None,
            
            # Airtel fields
            airtel_number=airtel_config.phone_number if airtel_config else None,
            
            # Bank fields (aligned with new model columns)
            bank_name=bank_config.bank_name if bank_config else None,
            bank_account_number=bank_config.account_number if bank_config else None,
            bank_account_name=bank_config.account_name if bank_config else None,
            branch_code=bank_config.branch_code if bank_config else None,
            swift_code=bank_config.swift_code if bank_config else None,
            currency=bank_config.currency if bank_config else None,
            
            # Fallback: tenant profile phone for "Send Money"
            tenant_phone=profile.phone if profile else None,
        )

    return PublicInvoiceView(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
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
        # ✅ MILESTONE 2: Driver fields (null for self-drive)
        driver_name=driver.full_name if driver else None,
        driver_phone=driver.phone if driver else None,
        driver_dl_number=driver.dl_number if driver else None,
        payment_details=payment_details,
    )


@router.get("/public/{token}", response_model=PublicInvoiceView)
@limiter.limit("30/minute")
async def view_invoice_public(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Invoice).where(Invoice.share_token == token)
    result = await db.execute(stmt)
    invoice = result.scalars().first()

    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invoice link has expired")

    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invoice has been voided")

    return await _build_public_view(db, invoice.id)


@router.post("/public/{token}/pay", response_model=PublicInvoiceView)
@limiter.limit("10/minute")
async def record_payment_public(
    request: Request,
    token: str,
    payload: PublicPaymentCreate,
    db: AsyncSession = Depends(get_db)
):
    """✅ Client self-reported payment on the public portal."""
    stmt = select(Invoice).where(Invoice.share_token == token)
    result = await db.execute(stmt)
    invoice = result.scalars().first()

    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invoice link has expired")

    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot record payment against a void invoice")

    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invoice is already fully paid")

    remaining = (invoice.amount_due or Decimal("0")) - (invoice.amount_paid or Decimal("0"))
    if payload.amount > remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount exceeds remaining balance of {remaining} {invoice.currency_code}"
        )

    now = datetime.now(timezone.utc)

    db_payment = Payment(
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        amount=payload.amount,
        currency_code=invoice.currency_code,
        method=payload.method,
        reference=payload.reference,
        status=PaymentStatus.completed,
        paid_at=now,
        recorded_by=None,
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
async def download_invoice_pdf_public(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Invoice).where(Invoice.share_token == token)
    result = await db.execute(stmt)
    invoice = result.scalars().first()

    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invoice link has expired")

    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invoice has been voided")

    pdf_bytes = await generate_invoice_pdf(invoice, db)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{invoice.invoice_number}.pdf"},
    )
