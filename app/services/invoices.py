# app/services/invoices.py
"""
Invoice creation/update for bookings.

✅ SINGLE SOURCE OF TRUTH: totals ALWAYS come from the pricing engine
(price_booking). No local day math anywhere in this file — the legacy
inclusive "+1 day" formula is removed. custom_rate overrides re-price the
booking through the engine (24h blocks + grace + overtime + driver stack),
so booking page, invoice, and contract can never disagree again.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.services.number_generator import generate_invoice_number
from app.services.cache import invalidate_booking_cache
from app.services.pricing import price_booking


async def create_invoice_for_booking(
    booking: Booking,
    db: AsyncSession,
    custom_amount: Optional[Decimal] = None,
    custom_currency: Optional[str] = None,
    custom_rate: Optional[Decimal] = None,
    discount_amount: Optional[Decimal] = None,
    discount_reason: Optional[str] = None,
    due_date_override: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> Invoice:
    """
    Create or update an invoice for a booking.

    Precedence for the invoice amount:
      custom_amount  >  engine total (after custom_rate override)  >  booking.total_amount

    When custom_rate is provided:
      - Writes booking.daily_rate (the override slot)
      - Re-prices via the pricing engine → booking.total_amount
      - Existing invoices follow the new total (Rate → Total mode)
    """
    # ✅ ASYNC: Check for existing invoice
    existing_stmt = select(Invoice).where(Invoice.booking_id == booking.id)
    existing_result = await db.execute(existing_stmt)
    existing_invoice = existing_result.scalars().first()

    # ✅ Rate override → engine re-price (never local day math)
    if custom_rate is not None:
        booking.daily_rate = custom_rate
        try:
            quote = await price_booking(db, booking, Decimal(custom_rate))
            booking.total_amount = quote.total
        except ValueError:
            # Invalid schedule edge case: keep last engine-priced total.
            pass
        await db.commit()
        await db.refresh(booking)
        await invalidate_booking_cache(booking.tenant_id)

    # If invoice already exists, update it with new values
    if existing_invoice:
        if custom_amount is not None:
            existing_invoice.amount_due = custom_amount
        elif custom_rate is not None:
            # ✅ Rate → Total: invoice follows the engine-recomputed total
            existing_invoice.amount_due = booking.total_amount
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

    # ✅ Determine final amount: custom_amount > engine-priced booking total
    if custom_amount is not None:
        final_amount = custom_amount
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
