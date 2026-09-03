# app/routers/booking/extensions.py
"""
✅ EXTEND | REDUCE | RESCHEDULE — CONTRACT v2: everything through the factory.

  POST /{id}/changes/quote → dry-run with honest delta (charge | credit | none)
  POST /{id}/changes       → commit (reprice-diff, conflict check, status matrix,
                             invoice doc synced, both datetime pairs mirrored)
  POST /{id}/extend        → legacy alias for the current frontend; delegates
                             to the factory so old calls get correct behavior.

Pricing: recompute-and-diff on the rate LOCKED at creation (rate × days intact).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.commission_lock import require_not_commission_locked
from app.models.bookings import Booking
from app.models.users import User
from app.schemas.booking import (
    BookingOut,
    ChangeBookingPayload,
    ChangeQuoteOut,
    ExtendBookingPayload,
)
from app.services import booking_factory
from ._helpers import get_authorized_booking_async

router = APIRouter()


async def _reload_with_relations(db: AsyncSession, booking_id: int) -> Booking:
    result = await db.execute(
        select(Booking).options(
            selectinload(Booking.client),
            selectinload(Booking.vehicle),
            selectinload(Booking.driver),
        ).where(Booking.id == booking_id)
    )
    return result.scalars().first()


# ---------------------------------------------------------------------------
# ✅ NEW CONTRACT: dry-run change (the modal shows this verbatim)
# ---------------------------------------------------------------------------
@router.post("/{booking_id}/changes/quote", response_model=ChangeQuoteOut)
@limiter.limit("30/minute")
async def quote_booking_change(
    request: Request,
    booking_id: int,
    payload: ChangeBookingPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    return await booking_factory.quote_change(
        db, booking,
        new_pickup_raw=payload.new_pickup_at,
        new_return_raw=payload.new_return_at,
    )


# ---------------------------------------------------------------------------
# ✅ NEW CONTRACT: commit a quoted change
# ---------------------------------------------------------------------------
@router.post("/{booking_id}/changes", response_model=ChangeQuoteOut)
@limiter.limit("10/minute")  # 🚨 financial mutation
async def apply_booking_change(
    request: Request,
    booking_id: int,
    payload: ChangeBookingPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    return await booking_factory.apply_change(
        db, booking, user=current_user,
        new_pickup_raw=payload.new_pickup_at,
        new_return_raw=payload.new_return_at,
        note=payload.note,
    )


# ---------------------------------------------------------------------------
# ✅ LEGACY ALIAS: old frontend POSTs ExtendBookingPayload here.
#    Delegates to the factory — correct pricing, conflicts, statuses, snapshots.
#    (Completed/cancelled bookings now correctly reject with 422.)
# ---------------------------------------------------------------------------
@router.post("/{booking_id}/extend", response_model=BookingOut)
@limiter.limit("10/minute")
async def extend_booking(
    request: Request,
    booking_id: int,
    payload: ExtendBookingPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    await booking_factory.apply_change(
        db, booking, user=current_user,
        new_return_raw=payload.new_end_date,
        note=payload.extension_reason,
    )
    return await _reload_with_relations(db, booking_id)
