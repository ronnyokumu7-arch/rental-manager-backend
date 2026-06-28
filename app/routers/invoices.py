# app/routers/invoices.py
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.invoices import Invoice, InvoiceStatus
from app.models.users import User
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoiceUpdate
from app.services.invoices import create_invoice_for_booking

router = APIRouter(prefix="/invoices", tags=["invoices"])

# ─── LIST INVOICES ───────────────────────────────────────────────────────────
@router.get("/", response_model=list[InvoiceOut])
def list_invoices(
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    booking_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    query = db.query(Invoice).filter(Invoice.tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
    if booking_id is not None:
        query = query.filter(Invoice.booking_id == booking_id)
    return query.order_by(Invoice.created_at.desc()).all()

# ─── GET SINGLE INVOICE ───────────────────────────────────────────────────────
@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice

# ─── CREATE INVOICE (Manual Override) ────────────────────────────────────────
@router.post("/", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # We reuse the service to ensure consistent numbering & idempotency
    from app.models.bookings import Booking
    booking = db.query(Booking).filter(
        Booking.id == payload.booking_id,
        Booking.tenant_id == current_user.tenant_id
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found or access denied")

    # Inject notes if provided
    if payload.notes:
        # Temporarily attach notes to booking object for the service to use
        booking._override_notes = payload.notes 

    return create_invoice_for_booking(booking, db)

# ─── UPDATE INVOICE ───────────────────────────────────────────────────────────
@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    updates: InvoiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(invoice, field, value)

    db.commit()
    db.refresh(invoice)
    return invoice

# ─── DOWNLOAD PDF ─────────────────────────────────────────────────────────────
@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not invoice.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not yet generated")

    return FileResponse(
        invoice.pdf_path,
        media_type="application/pdf",
        filename=f"Invoice_{invoice.invoice_number}.pdf"
    )
