# app/routers/booking/lifecycle.py
"""
Booking lifecycle endpoints — THIN delegation layer.

✅ ALL transition logic lives in BookingLifecycleService (tenant-scoped,
row-locked, idempotent). Routers only handle auth, rate-limiting, and payload
parsing. Route paths are unchanged so the existing frontend keeps working
until Phase 5 updates labels/buttons.

Endpoints:
  POST /{id}/confirm    → service.confirm   (client-driven via quotation accept)
  POST /{id}/activate   → service.start_trip (from pending|confirmed)
  POST /{id}/complete   → service.complete  (sets actual_return_at + mileage_due)
  POST /{id}/cancel     → service.cancel(reason)
  POST /{id}/no-show    → alias for cancel(reason=no_show) [backward-compat]
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.subscription import require_active_subscription
from app.dependencies.commission_lock import require_not_commission_locked
from app.models.bookings import CancellationReason
from app.models.users import User
from app.schemas.booking import BookingOut, CancelBookingPayload
from app.services.booking_lifecycle import BookingLifecycleService

router = APIRouter()


@router.post("/{booking_id}/confirm", response_model=BookingOut)
@limiter.limit("20/minute")
async def confirm_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    """Confirm a pending booking. (Dashboard button removed in Phase 5;
    the public quotation-accept flow is the primary driver.)"""
    return await BookingLifecycleService.confirm(db, booking_id, current_user)


@router.post("/{booking_id}/activate", response_model=BookingOut)
@limiter.limit("20/minute")
async def activate_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Start the trip (from pending OR confirmed). Sets vehicle→rented + commission."""
    return await BookingLifecycleService.start_trip(db, booking_id, current_user)


@router.post("/{booking_id}/complete", response_model=BookingOut)
@limiter.limit("20/minute")
async def complete_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Complete the trip. Sets actual_return_at; vehicle→available + mileage_due."""
    return await BookingLifecycleService.complete(db, booking_id, current_user)


@router.post("/{booking_id}/cancel", response_model=BookingOut)
@limiter.limit("20/minute")
async def cancel_booking(
    request: Request,
    booking_id: int,
    payload: Optional[CancelBookingPayload] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """
    Cancel with a reason. Body optional for backward compat — defaults to
    agency_cancelled when omitted (operator-initiated).
    """
    reason = payload.reason if payload else CancellationReason.agency_cancelled
    return await BookingLifecycleService.cancel(db, booking_id, current_user, reason)


@router.post("/{booking_id}/no-show", response_model=BookingOut)
@limiter.limit("20/minute")
async def no_show_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """
    ✅ BACKWARD-COMPAT ALIAS: no_show is no longer a status — it's a cancel
    reason. Existing frontend "Mark no-show" buttons keep working; Phase 5
    migrates them to the cancel-with-reason modal.
    """
    return await BookingLifecycleService.cancel(
        db, booking_id, current_user, CancellationReason.no_show,
    )
