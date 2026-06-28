# app/routers/invoices.py
import random
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
# Optional: If you want to strictly enforce roles (uncomment if your rbac module is ready)
# from app.dependencies.rbac import require_role
# from app.models.users import UserRole

from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.models.users import User
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoiceUpdate

router = APIRouter(prefix="/invoices", tags=["invoices"])

def _generate_invoice_number() -> str:
    """Generates a unique invoice number like INV-2026-839201"""
    year = datetime.now().strftime("%Y")
    rand = ''.join(random.choices(string.digits, k=6))
    return f"INV-{year}-{rand}"

# ─── LIST INVOICES ───────────────────────────────────────────────────────────
@router.get("/", response_model=list[InvoiceOut])
def list_invoices(
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    # 🔒 SECURITY: Enforces login + active subscription (tenant check)
    current_user: User = Depends(require_active_subscription),
):
    # 🔒 SECURITY: Tenant Isolation - Only fetch invoices for THIS tenant
    query = db.query(Invoice).filter(Invoice.tenant_id == current_user.tenant_id)
    
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
        
    return query.order_by(Invoice.created_at.desc()).all()

# ─── GET SINGLE INVOICE ───────────────────────────────────────────────────────
@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # 🔒 SECURITY: Filter by ID AND Tenant ID to prevent IDOR attacks
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice

# ─── CREATE INVOICE ───────────────────────────────────────────────────────────
@router.post("/", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    #  SECURITY: Verify the booking belongs to this tenant before creating an invoice
    booking = db.query(Booking).filter(
        Booking.id == payload.booking_id,
        Booking.tenant_id == current_user.tenant_id
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found or access denied")

    # Check if invoice already exists for this booking
    existing_invoice = db.query(Invoice).filter(Invoice.booking_id == booking.id).first()
    if existing_invoice:
        raise HTTPException(status_code=409, detail="An invoice already exists for this booking")

    db_invoice = Invoice(
        tenant_id=current_user.tenant_id,
        booking_id=booking.id,
        invoice_number=_generate_invoice_number(),
        status=InvoiceStatus.draft,
        amount_due=booking.total_amount,
        amount_paid=0,
        currency_code=booking.currency_code or "KES",
        due_date=payload.due_date,
        notes=payload.notes,
    )
    
    db.add(db_invoice)
    db.commit()
    db.refresh(db_invoice)
    return db_invoice

# ─── UPDATE INVOICE ───────────────────────────────────────────────────────────
@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    updates: InvoiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # 🔒 SECURITY: Tenant Isolation
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

# ─── VOID INVOICE ─────────────────────────────────────────────────────────────
@router.post("/{invoice_id}/void", response_model=InvoiceOut)
def void_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    #  SECURITY: Tenant Isolation
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(status_code=400, detail="Cannot void a paid invoice")

    invoice.status = InvoiceStatus.void
    db.commit()
    db.refresh(invoice)
    return invoice
