from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.invoices import Invoice
from app.models.payments import Payment, PaymentMethod, PaymentStatus
from app.models.users import User
from app.schemas.payment import PaymentOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import (
    get_cached_payment_list,
    set_cached_payment_list,
)
from ._helpers import get_authorized_payment_async

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[PaymentOut])
@limiter.limit("60/minute")
async def list_payments(
    request: Request,
    invoice_id: Optional[int] = Query(None),
    status_filter: Optional[PaymentStatus] = Query(None, alias="status"),
    method_filter: Optional[PaymentMethod] = Query(None, alias="method"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """
    ✅ SECURITY: Manual tenant-scoped caching.
    Default @cache decorator does NOT include tenant context, causing cross-tenant leaks.
    """
    # Check cache first
    cached = await get_cached_payment_list(
        current_user.tenant_id,
        invoice_id=invoice_id,
        status_filter=status_filter.value if status_filter else None,
        method_filter=method_filter.value if method_filter else None,
    )
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)

    stmt = select(Payment).options(
        selectinload(Payment.invoice)
        .selectinload(Invoice.booking)
        .selectinload(Booking.client)
    ).where(Payment.tenant_id == current_user.tenant_id)

    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if status_filter is not None:
        stmt = stmt.where(Payment.status == status_filter)
    if method_filter is not None:
        stmt = stmt.where(Payment.method == method_filter)

    stmt = stmt.order_by(Payment.created_at.desc())
    result = await db.execute(stmt)
    payments = result.scalars().unique().all()
    
    # Write to cache (5-minute TTL)
    await set_cached_payment_list(
        current_user.tenant_id,
        invoice_id=invoice_id,
        status_filter=status_filter.value if status_filter else None,
        method_filter=method_filter.value if method_filter else None,
        payments=payments,
    )
    
    return paginate_items(payments, total=len(payments), page=page, page_size=page_size)


@router.get("/{payment_id}", response_model=PaymentOut)
@limiter.limit("60/minute")
async def get_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """
    Single payment lookup. Not cached (low frequency, high security risk if cached incorrectly).
    The helper enforces tenant isolation.
    """
    stmt = select(Payment).options(
        selectinload(Payment.invoice)
        .selectinload(Invoice.booking)
        .selectinload(Booking.client)
    ).where(
        Payment.id == payment_id,
        Payment.tenant_id == current_user.tenant_id
    )
    
    result = await db.execute(stmt)
    payment = result.scalars().unique().first()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )
    
    return payment


@router.get("/export/csv")
@limiter.limit("10/minute")
async def export_payments_csv(
    request: Request,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """
    Export payments as CSV. Tenant-scoped.
    Note: /export/csv route must be defined BEFORE /{payment_id} to avoid path conflicts.
    """
    stmt = select(Payment, Invoice.invoice_number).join(
        Invoice, Payment.invoice_id == Invoice.id
    ).where(Payment.tenant_id == current_user.tenant_id)

    if start_date:
        stmt = stmt.where(Payment.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Payment.created_at <= end_date)

    stmt = stmt.order_by(Payment.created_at.desc())
    result = await db.execute(stmt)
    results = result.all()

    headers = ["ID", "Invoice Number", "Amount", "Currency", "Method", "Reference", "Status", "Recorded By", "Date"]
    rows = [
        [
            str(p.id),
            inv_num or "",
            str(p.amount),
            p.currency_code,
            p.method.value,
            p.reference or "",
            p.status.value,
            str(p.recorded_by or ""),
            p.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        ]
        for p, inv_num in results
    ]

    csv_content = "\n".join([",".join(headers)] + [",".join(row) for row in rows])

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments_export.csv"},
    )
