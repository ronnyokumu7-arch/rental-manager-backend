# app/routers/payment/management.py
"""
✅ PAYMENT MANAGEMENT — list / get / CSV export (tenant-scoped, cached).

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B):
  - Export date params parsed + validated (was: string vs datetime column → 500).
  - CSV built with the csv module (proper quoting; commas no longer break columns).
"""
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationFailedError
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


def _parse_export_date(value: str, field: str) -> datetime:
    """✅ Phase B: strict YYYY-MM-DD parsing (was: raw string vs datetime column)."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise ValidationFailedError(
            title="Invalid Date",
            message="Export dates must use the YYYY-MM-DD format.",
            field_errors={field: "Use YYYY-MM-DD"},
        )


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

    # ✅ Phase B: validated datetime bounds (inclusive end day)
    if start_date:
        stmt = stmt.where(Payment.created_at >= _parse_export_date(start_date, "start_date"))
    if end_date:
        end_exclusive = _parse_export_date(end_date, "end_date") + timedelta(days=1)
        stmt = stmt.where(Payment.created_at < end_exclusive)

    stmt = stmt.order_by(Payment.created_at.desc())
    result = await db.execute(stmt)
    results = result.all()

    headers = ["ID", "Invoice Number", "Amount", "Currency", "Method", "Reference", "Status", "Recorded By", "Date"]

    # ✅ Phase B: csv module = correct quoting (commas/newlines in references)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for p, inv_num in results:
        writer.writerow([
            str(p.id),
            inv_num or "",
            str(p.amount),
            p.currency_code,
            p.method.value,
            p.reference or "",
            p.status.value,
            str(p.recorded_by or ""),
            p.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        ])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments_export.csv"},
    )


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
        raise NotFoundError(
            title="Payment Not Found",
            message="We couldn't find this payment, or you may not have access to it.",
        )
    
    return payment
