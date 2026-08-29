"""
Invoice → Booking synchronization.

When an operator edits an invoice's amount_due, propagate the new total to
the linked booking so the backend "knows" about the human price adjustment.

Rules:
  - booking.total_amount    ← invoice.amount_due
  - booking.manually_adjusted = True
  - booking.price_note      ← audit trail referencing the invoice
  - booking.computed_total is NEVER touched (engine truth stays immutable)

The caller commits atomically — this service only mutates in-memory state.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.invoices import Invoice


async def sync_invoice_to_booking(
    db: AsyncSession, invoice: Invoice,
) -> Booking | None:
    """
    Propagate invoice.amount_due to the linked booking.total_amount.

    Args:
        db: Active async session (caller commits).
        invoice: Invoice instance whose amount_due was just updated.

    Returns:
        The mutated Booking, or None if the invoice has no linked booking.
    """
    if not invoice.booking_id:
        return None  # standalone invoice — nothing to sync

    stmt = select(Booking).where(Booking.id == invoice.booking_id)
    booking = (await db.execute(stmt)).scalars().first()
    if not booking:
        return None  # booking deleted — invoice survives for audit

    # ✅ Human override lands on the booking; engine snapshot stays immutable
    booking.total_amount = invoice.amount_due
    booking.manually_adjusted = True
    booking.price_note = f"Price adjusted via invoice {invoice.invoice_number}"

    return booking
