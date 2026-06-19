from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.invoices import Invoice, InvoiceStatus
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoiceUpdate
from app.services.email import send_invoice_notification
from app.services.pdf import generate_invoice_pdf


router = APIRouter(prefix="/invoices", tags=["invoices"])

# The Bouncer
super_admin_only = Depends(require_role([UserRole.super_admin]))


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_authorized_invoice(invoice_id: int, user: User, db: Session) -> Invoice:
    """Helper to retrieve invoice and enforce ownership/access control."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )
    
    # Super admins see all, regular users only their own
    if user.role != UserRole.super_admin and invoice.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own invoices",
        )
    return invoice


def _generate_invoice_number(tenant_id: int, db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.query(Invoice).filter(
        Invoice.tenant_id == tenant_id,
    ).count()
    sequence = str(count + 1).zfill(4)
    return f"{tenant_id}-{year}-{sequence}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    invoice_number = _generate_invoice_number(payload.tenant_id, db)
    db_invoice = Invoice(
        **payload.model_dump(),
        invoice_number=invoice_number,
        status=InvoiceStatus.draft,
        amount_paid=Decimal("0"),
    )
    db.add(db_invoice)
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.get("/", response_model=list[InvoiceOut])
def list_invoices(
    invoice_status: InvoiceStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Invoice)
    if current_user.role != UserRole.super_admin:
        query = query.filter(Invoice.tenant_id == current_user.tenant_id)
    if invoice_status is not None:
        query = query.filter(Invoice.status == invoice_status)
    return query.order_by(Invoice.created_at.desc()).all()


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_authorized_invoice(invoice_id, current_user, db)


@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    # For super_admin updates, we just need to verify existence (no ownership check needed for super admins)
    # Reusing helper is safe if we pass the current_user
    invoice = _get_authorized_invoice(invoice_id, current_user, db)
    
    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.void):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit a {invoice.status.value} invoice",
        )
        
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(invoice, field, value)
        
    db.commit()
    db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/send", response_model=InvoiceOut)
def send_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    invoice = _get_authorized_invoice(invoice_id, current_user, db)
    
    if invoice.status != InvoiceStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only draft invoices can be sent. Current status: '{invoice.status.value}'",
        )
        
    invoice.status = InvoiceStatus.sent
    db.commit()
    db.refresh(invoice)
    
    tenant = db.query(Tenant).filter(Tenant.id == invoice.tenant_id).first()
    if tenant:
        send_invoice_notification(
            to=tenant.email,
            company_name=tenant.name,
            invoice_number=invoice.invoice_number,
            amount_due=str(invoice.amount_due),
            currency=invoice.currency_code,
            due_date=invoice.due_date.strftime("%d %b %Y"),
        )
    return invoice


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
def void_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    invoice = _get_authorized_invoice(invoice_id, current_user, db)
    
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paid invoices cannot be voided",
        )
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already void",
        )
        
    invoice.status = InvoiceStatus.void
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}/pdf")
def get_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invoice = _get_authorized_invoice(invoice_id, current_user, db)
    
    pdf_bytes = generate_invoice_pdf(invoice, db)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=invoice-{invoice.invoice_number}.pdf"
        },
    )