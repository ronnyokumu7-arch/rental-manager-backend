from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentStatus
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.payment import PaymentCreate, PaymentOut
from app.services.email import send_payment_received


router = APIRouter(prefix="/payments", tags=["payments"])

# The Bouncer
super_admin_only = Depends(require_role([UserRole.super_admin]))


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_authorized_payment(payment_id: int, user: User, db: Session) -> Payment:
    """Helper to retrieve payment and enforce ownership/access control."""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    
    # Super admins see all, regular users only their own
    if user.role != UserRole.super_admin and payment.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own payments",
        )
    return payment


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    invoice = db.query(Invoice).filter(Invoice.id == payload.invoice_id).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )
    
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot record payment against a void invoice",
        )
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already fully paid",
        )

    now = datetime.now(timezone.utc)
    
    # Record payment
    db_payment = Payment(
        invoice_id=payload.invoice_id,
        tenant_id=invoice.tenant_id,
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

    # Update invoice
    invoice.amount_paid = (invoice.amount_paid or 0) + payload.amount
    if invoice.amount_paid >= invoice.amount_due:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now

    db.commit()
    db.refresh(db_payment)
    
    # Send receipt
    tenant = db.query(Tenant).filter(Tenant.id == db_payment.tenant_id).first()
    if tenant:
        send_payment_received(
            to=tenant.email,
            company_name=tenant.name,
            invoice_number=invoice.invoice_number,
            amount_paid=str(payload.amount),
            currency=payload.currency_code,
        )
        
    return db_payment


@router.get("/", response_model=list[PaymentOut])
def list_payments(
    invoice_id: int | None = None,
    tenant_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    query = db.query(Payment)
    if invoice_id is not None:
        query = query.filter(Payment.invoice_id == invoice_id)
    if tenant_id is not None:
        query = query.filter(Payment.tenant_id == tenant_id)
    return query.order_by(Payment.created_at.desc()).all()


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    return _get_authorized_payment(payment_id, current_user, db)