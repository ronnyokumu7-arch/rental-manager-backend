# app/routers/booking/management_lifecycle.py
"""UPDATE / ARCHIVE / RESTORE / DELETE — post-creation lifecycle.

✅ PHASE 1: re-pricing on schedule/rate change via the pure self-drive engine
(quote_selfdrive). Manual total overrides via PATCH are tracked as
manually_adjusted with an audit note.

✅ ACTIVITY FEED: loggers run on eager-loaded snapshots and are committed
(flush-only loggers + post-commit calls require an explicit commit).
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking, BookingStatus
from app.models.drivers import Driver
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.booking import BookingOut, BookingUpdate
from app.services.cache import invalidate_booking_cache
from app.services.pricing_selfdrive import quote_selfdrive  # ✅ PHASE 1: pure engine
from ._helpers import get_authorized_booking_async
# ✅ MILESTONE 2: shared tenant-scoped driver validator (defined in create)
from .management_create import validate_driver_assignment
# ✅ NEW: Activity Logger for booking updates/archives
from app.services.activity_logs.booking import BookingActivityLogger

router = APIRouter()


async def _reload_full(db: AsyncSession, booking_id: int) -> Booking:
    """✅ Eager re-fetch: loaded relationships = rich log summaries + safe serialization."""
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver),
    ).where(Booking.id == booking_id)
    return (await db.execute(stmt)).scalars().first()


@router.patch("/{booking_id}", response_model=BookingOut)
@limiter.limit("30/minute")
async def update_booking(
    request: Request,
    booking_id: int,
    booking_update: BookingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    update_data = booking_update.model_dump(exclude_unset=True)

    # ✅ PHASE 1: driver optional for self-drive (old 422 guard removed)
    target_driver_id = update_data.get("driver_id", booking.driver_id)

    # ✅ MILESTONE 2: Validate driver on reassign; allow null to unassign
    if "driver_id" in update_data and update_data["driver_id"] is not None:
        await validate_driver_assignment(
            db, current_user.tenant_id, update_data["driver_id"]
        )

    # ✅ MILESTONE 1: effective post-update schedule (times → dates fallback)
    target_pickup = (
        update_data.get("pickup_at")
        or update_data.get("start_date")
        or booking.pickup_at
        or booking.start_date
    )
    target_return = (
        update_data.get("scheduled_return_at")
        or update_data.get("end_date")
        or booking.scheduled_return_at
        or booking.end_date
    )

    # ✅ DOUBLE BOOKING PREVENTION (time-exact, excludes self, coalesce-safe)
    schedule_changed = any(
        k in update_data
        for k in ("start_date", "end_date", "pickup_at", "scheduled_return_at", "service_type")
    )
    if schedule_changed:
        overlap_stmt = select(Booking).where(
            Booking.vehicle_id == booking.vehicle_id,
            Booking.tenant_id == current_user.tenant_id,
            Booking.is_archived == False,
            Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed, BookingStatus.active]),
            Booking.id != booking.id,
            and_(
                func.coalesce(Booking.pickup_at, Booking.start_date) < target_return,
                func.coalesce(Booking.scheduled_return_at, Booking.end_date) > target_pickup,
            )
        )
        overlap_result = await db.execute(overlap_stmt)
        if overlap_result.scalars().first():
            raise HTTPException(status_code=409, detail="This vehicle is already booked for the selected dates.")

    # ✅ PHASE 1: Re-price when schedule OR rate changes (server = source of truth)
    reprice_needed = schedule_changed or "daily_rate" in update_data
    if reprice_needed:
        vehicle_stmt = select(Vehicle).where(Vehicle.id == booking.vehicle_id)
        vehicle = (await db.execute(vehicle_stmt)).scalars().first()

        # Precedence: new override → existing effective rate → vehicle default
        daily_rate = (
            update_data.get("daily_rate")
            or booking.daily_rate
            or (vehicle.daily_rate if vehicle else None)
        )
        if not daily_rate or Decimal(daily_rate) <= 0:
            raise HTTPException(status_code=400, detail="Booking has no daily rate configured.")

        # Driver fee via explicit query (never lazy-load in async context)
        driver_daily_fee = None
        if target_driver_id is not None:
            driver = (await db.execute(
                select(Driver).where(Driver.id == target_driver_id)
            )).scalars().first()
            if driver:
                driver_daily_fee = driver.daily_fee

        try:
            quote = quote_selfdrive(
                pickup_at=target_pickup,
                return_at=target_return,
                daily_rate=Decimal(daily_rate),
                driver_daily_fee=Decimal(driver_daily_fee) if driver_daily_fee else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # New terms → engine truth (operator can re-adjust afterwards)
        update_data["daily_rate"] = daily_rate
        update_data["billable_days"] = quote.billable_days
        update_data["computed_total"] = quote.total
        update_data["total_amount"] = quote.total
        update_data["manually_adjusted"] = False
        update_data["price_note"] = None

    # ✅ PHASE 1: explicit total override = human adjustment (audit-tracked)
    if "total_amount" in update_data:
        update_data["manually_adjusted"] = True
        update_data["price_note"] = (
            f"Manually adjusted via booking update by user {current_user.id}"
        )

    for field, value in update_data.items():
        setattr(booking, field, value)

    await db.commit()

    # ✅ Eager snapshot for logging + response (rich summaries, no lazy-load)
    booking_full = await _reload_full(db, booking.id)

    await invalidate_booking_cache(current_user.tenant_id)

    # ✅ NEW: Log booking update event
    try:
        await BookingActivityLogger.on_updated(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            booking=booking_full,
            changed_fields=list(update_data.keys()),
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log booking update: {e}")

    # ✅ CRITICAL: persist the flushed activity log
    await db.commit()

    return booking_full


@router.post("/{booking_id}/archive", response_model=BookingOut)
@limiter.limit("10/minute")
async def archive_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)

    if booking.status == BookingStatus.active:
        raise HTTPException(status_code=400, detail="Active bookings cannot be archived")
    if booking.is_archived:
        raise HTTPException(status_code=400, detail="Booking is already archived")

    booking.is_archived = True
    booking.archived_at = datetime.now(timezone.utc)
    await db.commit()

    booking_full = await _reload_full(db, booking.id)

    await invalidate_booking_cache(current_user.tenant_id)

    # ✅ NEW: Log booking archive event
    try:
        await BookingActivityLogger.on_archived(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            booking=booking_full,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log booking archive: {e}")

    # ✅ CRITICAL: persist the flushed activity log
    await db.commit()

    return booking_full


@router.post("/{booking_id}/restore", response_model=BookingOut)
@limiter.limit("10/minute")
async def restore_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)

    if not booking.is_archived:
        raise HTTPException(status_code=400, detail="Booking is not archived")

    booking.is_archived = False
    booking.archived_at = None
    await db.commit()

    booking_full = await _reload_full(db, booking.id)

    await invalidate_booking_cache(current_user.tenant_id)

    # ✅ NEW: Log booking restore event
    try:
        await BookingActivityLogger.on_restored(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            booking=booking_full,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log booking restore: {e}")

    # ✅ CRITICAL: persist the flushed activity log
    await db.commit()

    return booking_full


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)

    if booking.status == BookingStatus.active:
        raise HTTPException(status_code=400, detail="Active bookings cannot be deleted.")

    try:
        await db.delete(booking)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Cannot delete booking with invoices or contracts. Please archive instead."
        )

    await invalidate_booking_cache(current_user.tenant_id)
