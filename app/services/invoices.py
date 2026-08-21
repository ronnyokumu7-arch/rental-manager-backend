from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.services.number_generator import generate_invoice_number
from app.services.cache import invalidate_booking_cache


async def create_invoice_for_booking(
    booking: Booking,
    db: AsyncSession,
    custom_amount: Optional[Decimal] = None,
    custom_currency: Optional[str] = None,
    custom_rate: Optional[Decimal] = None,
    discount_amount: Optional[Decimal] = None,
    discount_reason: Optional[str] = None,
    due_date_override: Optional = None,
    notes: Optional[str] = None,
) -> Invoice:
    """
    Create or update an invoice for a booking.
    
    When custom_rate is provided:
      - Writes to booking.daily_rate (the override slot)
      - Recomputes booking.total_amount = rate × inclusive_days
      - Contract will then render the updated rate and total
    
    Args:
        booking: The booking to invoice
        custom_amount: Override total amount (takes precedence over rate calculation)
        custom_rate: Override daily rate (computes total from rate × days)
        ...
    """
    # ✅ ASYNC: Check for existing invoice
    existing_stmt = select(Invoice).where(Invoice.booking_id == booking.id)
    existing_result = await db.execute(existing_stmt)
    existing_invoice = existing_result.scalars().first()
    
    # ✅ NEW: Apply rate override to booking (whether invoice exists or not)
    if custom_rate is not None:
        booking.daily_rate = custom_rate
        
        # Recompute total from rate × inclusive days
        if booking.start_date and booking.end_date:
            inclusive_days = (booking.end_date - booking.start_date).days + 1
            booking.total_amount = custom_rate * inclusive_days
        
        await db.commit()
        await db.refresh(booking)
        await invalidate_booking_cache(booking.tenant_id)
    
    # If invoice already exists, update it with new values
    if existing_invoice:
        if custom_amount is not None:
            existing_invoice.amount_due = custom_amount
        if custom_currency is not None:
            existing_invoice.currency_code = custom_currency
        if discount_amount is not None:
            existing_invoice.discount_amount = discount_amount
        if discount_reason is not None:
            existing_invoice.discount_reason = discount_reason
        if due_date_override is not None:
            existing_invoice.due_date = due_date_override
        if notes is not None:
            existing_invoice.notes = notes
        
        await db.commit()
        await db.refresh(existing_invoice)
        return existing_invoice
    
    # Generate invoice number (Centralized, tenant-scoped, monthly-resetting)
    # Format: I{YYYY}{MM}{###} (e.g., I202607001)
    invoice_number = await generate_invoice_number(db, booking.tenant_id)
    
    # Determine final amount: custom_amount > computed from rate > booking.total_amount
    if custom_amount is not None:
        final_amount = custom_amount
    elif custom_rate is not None and booking.start_date and booking.end_date:
        inclusive_days = (booking.end_date - booking.start_date).days + 1
        final_amount = custom_rate * inclusive_days
    else:
        final_amount = booking.total_amount
    
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
