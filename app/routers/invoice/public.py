from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.invoices import Invoice, InvoiceStatus
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle
from app.schemas.invoice import PublicInvoiceView
from app.services.invoice_pdf import generate_invoice_pdf

# ✅ No prefix here! The hub file provides the "/invoices" prefix.
router = APIRouter()


@router.get("/public/{token}", response_model=PublicInvoiceView)
@limiter.limit("30/minute")
async def view_invoice_public(
    request: Request,
    token: str, 
    db: AsyncSession = Depends(get_db)
):
    # ✅ Optimized: Fetch all related data in a single query using selectinload
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
        selectinload(Invoice.tenant)
    ).where(Invoice.share_token == token)
    
    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invoice link has expired"
        )
    
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invoice has been voided"
        )

    booking = invoice.booking
    client = booking.client if booking else None
    vehicle = booking.vehicle if booking else None
    tenant = invoice.tenant

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
        vehicle_description=f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})" if vehicle else "N/A",
        booking_start_date=str(booking.start_date) if booking else None,
        booking_end_date=str(booking.end_date) if booking else None,
    )


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    if invoice.share_token_expires_at and invoice.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invoice link has expired"
        )
    
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invoice has been voided"
        )

    # ✅ Await the async PDF generation
    pdf_bytes = await generate_invoice_pdf(invoice, db)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{invoice.invoice_number}.pdf"},
    )
