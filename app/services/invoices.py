"""
Invoice + Quotation creation/update for bookings.

✅ PHASE 1 SINGLE SOURCE OF TRUTH:
  - Totals come from the booking snapshot (booking.total_amount / computed_total).
  - Rate overrides (custom_rate) re-price via the pure self-drive engine
    (quote_selfdrive). No legacy config tables, no local day math.

✅ LIFECYCLE (quotation pipeline):
  - create_quotation_for_booking  → auto-called on booking create (doc_type=quotation)
  - morph_quotation_to_invoice    → called on client accept (quotation → invoice,
                                    due_date = rental start)
  New functions flush (don't commit) so callers commit atomically.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.drivers import Driver
from app.models.invoices import Invoice, InvoiceStatus
from app.services.number_generator import generate_invoice_number
from app.services.cache import invalidate_booking_cache
from app.services.pricing_selfdrive import compute_billable_days, quote_selfdrive

# Quotation public link validity (days)
QUOTATION_VALID_DAYS = 7


def _rental_start(booking: Booking) -> datetime:
    """Exact pickup time, falling back to start_date."""
    return booking.pickup_at or booking.start_date


def _ensure_share_token(invoice: Invoice, days: int = QUOTATION_VALID_DAYS) -> None:
    now = datetime.now(timezone.utc)
    if not invoice.share_token or (
        invoice.share_token_expires_at and invoice.share_token_expires_at < now
    ):
        invoice.share_token = str(uuid.uuid4())
        invoice.share_token_expires_at = now + timedelta(days=days)


# =============================================================================
# EXISTING: manual invoice generation (Phase 1 re-pricing)
# =============================================================================
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
      custom_amount  >  engine total (after custom_rate re-price)  >  booking.total_amount
    """
    existing_stmt = select(Invoice).where(Invoice.booking_id == booking.id)
    existing_result = await db.execute(existing_stmt)
    existing_invoice = existing_result.scalars().first()

    if custom_rate is not None:
        # ✅ PHASE 1: override the effective rate for THIS booking only and
        # re-price through the pure self-drive engine (days × rate + driver fees).
        booking.daily_rate = custom_rate
        try:
            pickup_at = booking.pickup_at or booking.start_date
            return_at = booking.scheduled_return_at or booking.end_date

            # Locked day count when present (Phase 1 bookings); legacy rows recompute.
            days = booking.billable_days or compute_billable_days(pickup_at, return_at)

            # Driver fee (explicit query — never lazy-load in async context).
            driver_daily_fee = None
            if booking.driver_id:
                driver = (await db.execute(
                    select(Driver).where(Driver.id == booking.driver_id)
                )).scalars().first()
                if driver:
                    driver_daily_fee = driver.daily_fee

            quote = quote_selfdrive(
                pickup_at=pickup_at,
                return_at=return_at,
                daily_rate=Decimal(custom_rate),
                driver_daily_fee=(
                    Decimal(driver_daily_fee) if driver_daily_fee else None
                ),
            )
            booking.billable_days = quote.billable_days
            booking.computed_total = quote.total
            booking.total_amount = quote.total
        except ValueError:
            pass  # invalid schedule on legacy row — keep previous total
        await db.commit()
        await db.refresh(booking)
        await invalidate_booking_cache(booking.tenant_id)

    if existing_invoice:
        if custom_amount is not None:
            existing_invoice.amount_due = custom_amount
        elif custom_rate is not None:
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

    invoice_number = await generate_invoice_number(db, booking.tenant_id)

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

    await db.commit()
    await db.refresh(db_invoice)
    return db_invoice


# =============================================================================
# ✅ LIFECYCLE: Quotation pipeline (flush-only — caller commits atomically)
# =============================================================================
async def get_booking_quotation(db: AsyncSession, booking_id: int) -> Optional[Invoice]:
    """Return the booking's live quotation (doc_type=quotation), if any."""
    stmt = (
        select(Invoice)
        .where(Invoice.booking_id == booking_id, Invoice.doc_type == "quotation")
        .order_by(Invoice.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def create_quotation_for_booking(
    booking: Booking,
    db: AsyncSession,
    notes: Optional[str] = None,
) -> Invoice:
    """
    ✅ AUTO-CALLED on booking create. Creates the price offer the client accepts.

    - doc_type=quotation, status=sent (shareable immediately)
    - due_date = rental start (tentative; becomes the real due date on morph)
    - share_token generated so the public link is ready to send
    - Idempotent: returns the existing quotation if one already exists
    - FLUSH only — the caller (booking create) commits atomically
    """
    existing = await get_booking_quotation(db, booking.id)
    if existing:
        return existing

    invoice_number = await generate_invoice_number(db, booking.tenant_id)

    quotation = Invoice(
        tenant_id=booking.tenant_id,
        booking_id=booking.id,
        invoice_number=invoice_number,
        doc_type="quotation",
        status=InvoiceStatus.sent,
        amount_due=booking.total_amount,
        amount_paid=Decimal("0"),
        currency_code=booking.currency_code or "KES",
        discount_amount=Decimal("0"),
        due_date=_rental_start(booking),
        notes=notes,
    )
    _ensure_share_token(quotation)
    db.add(quotation)
    await db.flush()      # caller commits
    return quotation


async def morph_quotation_to_invoice(
    booking: Booking,
    db: AsyncSession,
) -> Optional[Invoice]:
    """
    ✅ CALLED on client accept. The quotation becomes the payable invoice.

    - doc_type: quotation → invoice
    - due_date = rental start (the initial payment due date)
    - amount re-synced from booking.total_amount (human adjustments included)
    - FLUSH only — the caller (accept flow) commits atomically
    Returns None if no quotation exists (nothing to morph).
    """
    quotation = await get_booking_quotation(db, booking.id)
    if not quotation:
        return None

    quotation.doc_type = "invoice"
    quotation.due_date = _rental_start(booking)
    quotation.amount_due = booking.total_amount
    if quotation.status == InvoiceStatus.draft:
        quotation.status = InvoiceStatus.sent
    _ensure_share_token(quotation)

    await db.flush()      # caller commits
    return quotation
