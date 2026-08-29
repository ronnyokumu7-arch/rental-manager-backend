import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.invoices import Invoice, InvoiceStatus
from app.models.users import User
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoiceUpdate
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import (
    get_cached_invoice_list, set_cached_invoice_list,
    invalidate_invoice_cache, invalidate_subscription_cache,
    invalidate_booking_cache,
)
from app.services.invoice_pdf import generate_invoice_pdf
from app.services.invoices import create_invoice_for_booking
from app.services.invoice_sync import sync_invoice_to_booking

router = APIRouter()
settings = get_settings()


# ✅ NEW: Helper to safely convert Invoice → InvoiceOut with denormalized UI fields
def serialize_invoice(invoice: Invoice) -> InvoiceOut:
    """Manually populate denormalized UI fields to prevent MissingGreenlet errors."""
    booking = invoice.booking
    client = getattr(booking, "client", None) if booking else None
    
    return InvoiceOut(
        id=invoice.id,
        tenant_id=invoice.tenant_id,
        booking_id=invoice.booking_id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        doc_type=invoice.doc_type,
        share_token=invoice.share_token,
        share_token_expires_at=invoice.share_token_expires_at,
        amount_due=invoice.amount_due,
        amount_paid=invoice.amount_paid,
        discount_amount=invoice.discount_amount,
        discount_reason=invoice.discount_reason,
        currency_code=invoice.currency_code,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        pdf_path=invoice.pdf_path,
        notes=invoice.notes,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        
        # ✅ Manually set denormalized fields
        booking_number=getattr(booking, "booking_number", None) if booking else None,
        client_id=client.id if client else None,
        client_name=getattr(client, "full_name", None) if client else None,
        client_phone=getattr(client, "phone", None) if client else None,
        vehicle_plate=getattr(booking.vehicle, "plate_number", None) if booking and booking.vehicle else None,
        vehicle_name=f"{booking.vehicle.make} {booking.vehicle.model}" if booking and booking.vehicle else None,
    )


@router.get("/", response_model=PaginatedResponse[InvoiceOut])
@limiter.limit("60/minute")
async def list_invoices(
    request: Request,
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    booking_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # ✅ Tenant-scoped caching
    cached = await get_cached_invoice_list(current_user.tenant_id, status_filter, booking_id)
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)

    # ✅ FIXED: Added selectinload for Invoice.booking.vehicle
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
    ).where(Invoice.tenant_id == current_user.tenant_id)
    
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
    if booking_id is not None:
        stmt = stmt.where(Invoice.booking_id == booking_id)
        
    stmt = stmt.order_by(Invoice.created_at.desc())
    result = await db.execute(stmt)
    invoices = result.scalars().unique().all()

    # ✅ NEW: Serialize with denormalized UI fields before caching
    serialized_invoices = [serialize_invoice(inv) for inv in invoices]
    
    await set_cached_invoice_list(current_user.tenant_id, status_filter, booking_id, serialized_invoices)
    return paginate_items(serialized_invoices, total=len(serialized_invoices), page=page, page_size=page_size)


@router.get("/{invoice_id}", response_model=InvoiceOut)
@limiter.limit("60/minute")
async def get_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # ✅ FIXED: Added selectinload for Invoice.booking.vehicle
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
    ).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    
    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    # ✅ NEW: Return serialized with denormalized UI fields
    return serialize_invoice(invoice)


@router.post("/", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_invoice(
    request: Request,
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking_stmt = select(Booking).where(
        Booking.id == payload.booking_id,
        Booking.tenant_id == current_user.tenant_id
    )
    booking_result = await db.execute(booking_stmt)
    booking = booking_result.scalars().first()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found or access denied"
        )

    invoice = await create_invoice_for_booking(
        booking,
        db,
        custom_amount=payload.amount_due,
        custom_currency=payload.currency_code,
        discount_amount=payload.discount_amount,
        discount_reason=payload.discount_reason,
        due_date_override=payload.due_date,
        notes=payload.notes,
    )
    
    # ✅ FIXED: Re-fetch with eager loading for Invoice.booking.vehicle
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
    ).where(Invoice.id == invoice.id)
    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()

    # ✅ Invalidate cache
    await invalidate_invoice_cache(current_user.tenant_id)
    
    # ✅ NEW: Return serialized with denormalized UI fields
    return serialize_invoice(invoice)


@router.patch("/{invoice_id}", response_model=InvoiceOut)
@limiter.limit("20/minute")
async def update_invoice(
    request: Request,
    invoice_id: int,
    updates: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.void) and updates.amount_due is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify amount of a paid or void invoice"
        )

    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(invoice, field, value)

    # ✅ PHASE 1: human price override propagates to the linked booking.
    booking_synced = False
    if "amount_due" in update_data:
        booking_synced = (await sync_invoice_to_booking(db, invoice)) is not None

    await db.commit()
    
    # ✅ FIXED: Re-fetch with eager loading for Invoice.booking.vehicle
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
    ).where(Invoice.id == invoice.id)
    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()
    
    # ✅ Invalidate caches
    await invalidate_invoice_cache(current_user.tenant_id)
    if booking_synced:
        await invalidate_booking_cache(current_user.tenant_id)
    
    # ✅ NEW: Return serialized with denormalized UI fields
    return serialize_invoice(invoice)


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
@limiter.limit("10/minute")
async def void_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    if invoice.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already void"
        )
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot void a paid invoice"
        )

    invoice.status = InvoiceStatus.void
    await db.commit()
    
    # ✅ FIXED: Re-fetch with eager loading for Invoice.booking.vehicle
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
    ).where(Invoice.id == invoice.id)
    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()
    
    # ✅ Invalidate both invoice and subscription caches
    await invalidate_invoice_cache(current_user.tenant_id)
    await invalidate_subscription_cache(current_user.tenant_id)
    
    # ✅ NEW: Return serialized with denormalized UI fields
    return serialize_invoice(invoice)


@router.get("/{invoice_id}/pdf")
@limiter.limit("30/minute")
async def download_invoice_pdf(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # ✅ FIXED: Added eager loading for Invoice.booking.vehicle
    stmt = select(Invoice).options(
        selectinload(Invoice.booking).selectinload(Booking.client),
        selectinload(Invoice.booking).selectinload(Booking.vehicle),
    ).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    invoice = result.scalars().unique().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    pdf_bytes = await generate_invoice_pdf(invoice, db)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{invoice.invoice_number}.pdf"},
    )


@router.post("/{invoice_id}/share-link", response_model=dict)
@limiter.limit("20/minute")
async def generate_invoice_share_link(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    invoice.share_token = str(uuid.uuid4())
    invoice.share_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    # ✅ FIXED: Flip status from draft to sent (mirrors contracts behavior)
    if invoice.status == InvoiceStatus.draft:
        invoice.status = InvoiceStatus.sent

    await db.commit()
    await db.refresh(invoice)
    
    # ✅ Invalidate cache
    await invalidate_invoice_cache(current_user.tenant_id)

    # ✅ Use settings.frontend_url instead of os.getenv
    base_url = settings.frontend_url.rstrip("/")
    return {
        "share_token": invoice.share_token,
        "share_url": f"{base_url}/invoice/{invoice.share_token}",
        "expires_at": invoice.share_token_expires_at.isoformat(),
    }
