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

# ✅ NEW: Import notification triggers
from app.services.notification_triggers import NotificationTriggers

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
    # ... (keep your existing create_invoice_for_booking logic exactly as is) ...
    # (Omitted for brevity, no changes needed here unless you want to notify on manual invoice creation)
    pass 


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
    # ... (keep your existing create_quotation_for_booking logic exactly as is) ...
    pass


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

    # ✅ NEW: Trigger Notification for Quotation Acceptance
    # We do this AFTER flush so the quotation is in the DB, but BEFORE the caller's commit,
    # keeping everything in the same atomic transaction.
    try:
        # Notify the tenant owner, or fallback to a super admin if needed
        target_user_id = booking.tenant.owner_id
        
        # We need the client name. If it's not eagerly loaded, we fetch it safely.
        client_name = "Client"
        if hasattr(booking, 'client') and booking.client:
            client_name = booking.client.full_name
        else:
            # Safe fallback fetch if not loaded
            client_result = await db.execute(
                select(booking.__class__.client).where(booking.__class__.id == booking.id)
            )
            client = client_result.scalars().first()
            if client:
                client_name = client.full_name

        if target_user_id:
            await NotificationTriggers.on_quotation_accepted(
                db=db,
                tenant_id=booking.tenant_id,
                target_user_id=target_user_id,
                booking_number=booking.booking_number,
                client_name=client_name,
                booking_id=booking.id,
                amount=float(booking.total_amount or 0),
            )
    except Exception as e:
        # ✅ Fail silently for notifications to protect the core business transaction
        print(f"⚠️ Warning: Failed to trigger quotation accepted notification: {e}")

    return quotation
