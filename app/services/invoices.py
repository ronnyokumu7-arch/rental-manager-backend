# app/services/invoices.py
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus

def _generate_invoice_number(tenant_id: int, db: Session) -> str:
    """
    Generates a clean, tenant-scoped invoice number.
    Format: T{tenant_id}-{sequence} (e.g., T1-001, T2-015)
    """
    prefix = f"T{tenant_id}-"
    
    # Fetch all invoices for this tenant to find the highest sequence number
    tenant_invoices = db.query(Invoice).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.invoice_number.like(f"{prefix}%")
    ).all()

    max_seq = 0
    for inv in tenant_invoices:
        try:
            # Extract the number part from "T1-001"
            seq_part = inv.invoice_number.split('-')[1]
            max_seq = max(max_seq, int(seq_part))
        except (IndexError, ValueError):
            continue

    next_seq = max_seq + 1
    # Format as 3 digits (e.g., 001, 002, 099, 100)
    return f"{prefix}{next_seq:03d}"

def create_invoice_for_booking(booking: Booking, db: Session) -> Invoice:
    """
    Creates a draft invoice for a confirmed booking.
    """
    # 1. Idempotency Check
    existing_invoice = db.query(Invoice).filter(Invoice.booking_id == booking.id).first()
    if existing_invoice:
        return existing_invoice

    # 2. Generate the new clean invoice number
    invoice_number = _generate_invoice_number(booking.tenant_id, db)

    # 3. Map Booking Data to Invoice Data
    db_invoice = Invoice(
        tenant_id=booking.tenant_id,
        booking_id=booking.id,
        invoice_number=invoice_number, # ✅ Using the new format
        status=InvoiceStatus.draft,
        amount_due=booking.total_amount,
        amount_paid=0,
        currency_code=booking.currency_code or "KES",
        due_date=booking.end_date,
        notes=f"Auto-generated invoice for Booking #{booking.id}",
    )
    
    db.add(db_invoice)
    db.commit()
    db.refresh(db_invoice)
    
    return db_invoice
