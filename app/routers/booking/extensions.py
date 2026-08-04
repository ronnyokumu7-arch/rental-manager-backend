import math
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking, BookingStatus
from app.models.invoices import Invoice, InvoiceStatus
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.booking import BookingOut, ExtendBookingPayload
from app.services.cache import invalidate_booking_cache, invalidate_vehicle_cache
from ._helpers import get_authorized_booking_async

router = APIRouter()


@router.post("/{booking_id}/extend", response_model=BookingOut)
@limiter.limit("10/minute")  # 🚨 Strict limit since this involves financial calculations
async def extend_booking(
    request: Request,
    booking_id: int,
    payload: ExtendBookingPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ✅ FIX: Use correct helper signature (booking_id, user, db)
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    if booking.status not in (BookingStatus.active, BookingStatus.completed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active or completed bookings can be extended."
        )
        
    if payload.new_end_date <= booking.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New end date must be strictly after the current end date."
        )
        
    # ✅ Async fetch for vehicle with tenant scoping (defense in depth)
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id
    )
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked vehicle not found."
        )

    # Record original end date for audit trail if not already set
    if booking.original_end_date is None:
        booking.original_end_date = booking.end_date

    # ✅ Robust day calculation: ceil partial days to ensure fair billing
    extra_seconds = (payload.new_end_date - booking.end_date).total_seconds()
    extra_days = max(1, math.ceil(extra_seconds / 86400))
    
    daily_rate = vehicle.daily_rate or Decimal("0")
    additional_cost = Decimal(str(extra_days)) * daily_rate

    booking.end_date = payload.new_end_date
    
    # ✅ Clean notes appending
    extension_note = f"[Extended]: {payload.extension_reason}" if payload.extension_reason else "[Extended]"
    if booking.notes:
        booking.notes = f"{booking.notes}\n{extension_note}"
    else:
        booking.notes = extension_note

    # ✅ Async fetch for invoice with tenant scoping
    invoice_stmt = select(Invoice).where(
        Invoice.booking_id == booking.id,
        Invoice.tenant_id == current_user.tenant_id
    )
    invoice_result = await db.execute(invoice_stmt)
    invoice = invoice_result.scalars().first()
    
    if invoice:
        invoice.amount_due = (invoice.amount_due or Decimal("0")) + additional_cost
        
        if invoice.status == InvoiceStatus.paid:
            invoice.status = InvoiceStatus.partially_paid
            
        invoice_note = f"[Extension Charge]: {extra_days} days @ {daily_rate}/day = {additional_cost}"
        if invoice.notes:
            invoice.notes = f"{invoice.notes}\n{invoice_note}"
        else:
            invoice.notes = invoice_note

    await db.commit()
    await db.refresh(booking)

    # ✅ Invalidate both booking and vehicle caches
    await invalidate_booking_cache(current_user.tenant_id)
    await invalidate_vehicle_cache(current_user.tenant_id)

    return booking
