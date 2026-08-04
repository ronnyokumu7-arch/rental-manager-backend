from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.services.number_generator import generate_invoice_number  # ✅ NEW: Centralized number generator


async def create_invoice_for_booking(
    booking: Booking,
    db: AsyncSession,
    custom_amount: Optional[Decimal] = None,
    custom_currency: Optional[str] = None,
    discount_amount: Optional[Decimal] = None,
    discount_reason: Optional[str] = None,
    due_date_override: Optional = None,
    notes: Optional[str] = None,
) -> Invoice:
    # ✅ ASYNC: Check for existing invoice
    existing_stmt = select(Invoice).where(Invoice.booking_id == booking.id)
    existing_result = await db.execute(existing_stmt)
    existing_invoice = existing_result.scalars().first()
    
    if existing_invoice:
        return existing_invoice

    # ✅ Generate invoice number (Centralized, tenant-scoped, monthly-resetting)
    # Format: I{YYYY}{MM}{###} (e.g., I202607001)
    invoice_number = await generate_invoice_number(db, booking.tenant_id)
    
    final_amount = custom_amount if custom_amount is not None else booking.total_amount
    final_currency = custom_currency or booking.currency_code or "KES"
    effective_discount = discount_amount or Decimal("0")

    db_invoice = Invoice(
        tenant_id=booking.tenant_id,
        booking_id=booking.id,
        invoice_number=invoice_number,
        status=InvoiceStatus.draft,
        amount_due=final_amount,
        amount_paid=Decimal("0"),
        currency_code=final_currency,
        discount_amount=effective_discount,
        discount_reason=discount_reason,
        due_date=due_date_override or booking.end_date,
        notes=notes,
    )
    db.add(db_invoice)
    
    # ✅ ASYNC: Commit and refresh
    await db.commit()
    await db.refresh(db_invoice)
    return db_invoice
