# app/routers/payments.py
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.users import User
from app.schemas.payment import PaymentCreate, PaymentOut

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Record a payment against an invoice."""
    # 1. Verify Invoice
    invoice = db.query(Invoice).filter(
        Invoice.id == payload.invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found or access denied")
        
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(status_code=400, detail="Cannot record payment against a void invoice")
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(status_code=400, detail="Invoice is already fully paid")

    now = datetime.now(timezone.utc)

    # 2. Create Payment Record
    db_payment = Payment(
        invoice_id=payload.invoice_id,
        tenant_id=current_user.tenant_id,
        amount=payload.amount,
        currency_code=payload.currency_code,
        method=payload.method,
        reference=payload.reference,
        status=PaymentStatus.completed,
        paid_at=now,
        recorded_by=current_user.id,
        notes=payload.notes,
    )
    db.add(db_payment)

    # 3. Update Invoice Totals
    invoice.amount_paid = (invoice.amount_paid or 0) + payload.amount
    if invoice.amount_paid >= invoice.amount_due:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now

    db.commit()
    db.refresh(db_payment)
    return db_payment

@router.get("/", response_model=list[PaymentOut])
def list_payments(
    invoice_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """List payments, optionally filtered by invoice_id."""
    query = db.query(Payment).filter(Payment.tenant_id == current_user.tenant_id)
    if invoice_id is not None:
        query = query.filter(Payment.invoice_id == invoice_id)
    return query.order_by(Payment.created_at.desc()).all()
