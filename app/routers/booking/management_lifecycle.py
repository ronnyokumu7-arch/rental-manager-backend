"""UPDATE / ARCHIVE / RESTORE / DELETE — post-creation lifecycle.

✅ PHASE 1 & MILESTONE 2 & 3: re-pricing on schedule/rate/add-on change via the 
pricing factory (quote_selfdrive / quote_airport_transfer / quote_wedding / quote_prodriver). 
Manual total overrides via PATCH are tracked as manually_adjusted with an audit note.

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
from app.services.pricing_airport import quote_airport_transfer  # ✅ MILESTONE 2: pure engine
from app.services.pricing_wedding import quote_wedding  # ✅ MILESTONE 3: pure engine
from app.services.pricing_prodriver import quote_prodriver  # ✅ MILESTONE 3: pure engine
from ._helpers import get_authorized_booking_async
# ✅ MILESTONE 2: shared tenant-scoped driver validator (defined in create)
from .management_create import validate_driver_assignment
# ✅ NEW: Activity Logger for booking updates/archives
from app.services.activity_logs.booking import BookingActivityLogger

router = APIRouter()

SELFDRIVE = "selfdrive"
AIRPORT_TRANSFER = "airport_transfer"
WEDDING = "wedding"
PRO_DRIVER = "pro_driver"


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

    # ✅ MILESTONE 2 & 3: Re-price when schedule, rate, add-ons, OR service_details change
    reprice_needed = (
        schedule_changed 
        or "daily_rate" in update_data 
        or "toll_fees" in update_data 
        or "parking_fees" in update_data
        or "service_details" in update_data
    )
    
    if reprice_needed:
        vehicle_stmt = select(Vehicle).where(Vehicle.id == booking.vehicle_id)
        vehicle = (await db.execute(vehicle_stmt)).scalars().first()

        # Determine which service type we are pricing for (fallback to existing)
        current_service_type = update_data.get("service_type", booking.service_type)

        if current_service_type == AIRPORT_TRANSFER:
            # ✅ Airport Transfer Pricing
            if not vehicle or not vehicle.supports_airport_transfer or not vehicle.airport_transfer_base_rate:
                raise HTTPException(status_code=400, detail="Vehicle does not support airport transfers or has no base rate.")
            
            # Extract add-ons (fallback to existing booking transfer record if not in payload)
            toll_fees = update_data.get("toll_fees", 0) or 0
            parking_fees = update_data.get("parking_fees", 0) or 0

            try:
                quote = quote_airport_transfer(
                    base_rate=Decimal(vehicle.airport_transfer_base_rate),
                    toll_fees=Decimal(toll_fees),
                    parking_fees=Decimal(parking_fees),
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

            # New terms → engine truth
            update_data["daily_rate"] = vehicle.airport_transfer_base_rate
            update_data["billable_days"] = 1
            update_data["computed_total"] = quote.total
            update_data["total_amount"] = quote.total
            update_data["manually_adjusted"] = False
            update_data["price_note"] = None

        elif current_service_type == WEDDING:
            # ✅ Wedding Pricing
            if not vehicle or not vehicle.supports_wedding_service or not vehicle.wedding_base_rate:
                raise HTTPException(status_code=400, detail="Vehicle does not support wedding services or has no base rate.")
            
            # Extract service-specific details from JSON payload (fallback to existing)
            details = update_data.get("service_details") or booking.service_details or {}
            extra_hours = int(details.get("extra_hours", 0))
            toll_fees = details.get("toll_fees", 0)
            decoration_fee = details.get("decoration_fee", 0)
            priority_booking_fee = details.get("priority_booking_fee", 0)
            fuel_fee = details.get("fuel_fee", 0)

            # Overtime rate: use assigned driver's fee if provided, else fallback to 0
            overtime_rate = 0
            if target_driver_id is not None:
                driver = (await db.execute(
                    select(Driver).where(Driver.id == target_driver_id)
                )).scalars().first()
                if driver:
                    overtime_rate = driver.overtime_hourly_fee or 0

            try:
                quote = quote_wedding(
                    base_rate=Decimal(vehicle.wedding_base_rate),
                    overtime_hourly_rate=Decimal(overtime_rate),
                    extra_hours=extra_hours,
                    toll_fees=Decimal(toll_fees),
                    decoration_fee=Decimal(decoration_fee),
                    priority_booking_fee=Decimal(priority_booking_fee),
                    fuel_fee=Decimal(fuel_fee),
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

            # New terms → engine truth
            update_data["daily_rate"] = vehicle.wedding_base_rate
            update_data["billable_days"] = 1
            update_data["computed_total"] = quote.total
            update_data["total_amount"] = quote.total
            update_data["manually_adjusted"] = False
            update_data["price_note"] = None

        elif current_service_type == PRO_DRIVER:
            # ✅ Pro Driver Pricing
            if not vehicle:
                raise HTTPException(status_code=400, detail="Vehicle not found.")
            if not target_driver_id:
                raise HTTPException(status_code=400, detail="Pro Driver service requires a staff driver assignment.")

            # Fetch driver for fees
            driver = (await db.execute(
                select(Driver).where(Driver.id == target_driver_id)
            )).scalars().first()
            if not driver:
                raise HTTPException(status_code=404, detail="Driver not found.")

            # Extract service-specific details from JSON payload
            details = update_data.get("service_details") or booking.service_details or {}
            extra_hours = int(details.get("extra_hours", 0))
            accommodation_fee = details.get("accommodation_fee", 0)
            toll_fees = details.get("toll_fees", 0)
            parking_fees = details.get("parking_fees", 0)

            # Calculate base rate (Vehicle daily rate + Driver daily fee)
            vehicle_daily_rate = Decimal(vehicle.daily_rate) if vehicle.daily_rate else Decimal("0.00")
            driver_daily_fee = Decimal(driver.daily_fee) if driver.daily_fee else Decimal("0.00")
            base_rate = vehicle_daily_rate + driver_daily_fee

            if base_rate <= 0:
                raise HTTPException(status_code=400, detail="Pro Driver base rate cannot be zero.")

            overtime_rate = Decimal(driver.overtime_hourly_fee) if driver.overtime_hourly_fee else Decimal("0.00")

            try:
                quote = quote_prodriver(
                    base_rate=base_rate,
                    overtime_hourly_rate=overtime_rate,
                    extra_hours=extra_hours,
                    accommodation_fee=Decimal(accommodation_fee),
                    toll_fees=Decimal(toll_fees),
                    parking_fees=Decimal(parking_fees),
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

            # New terms → engine truth
            update_data["daily_rate"] = base_rate
            update_data["billable_days"] = 1
            update_data["computed_total"] = quote.total
            update_data["total_amount"] = quote.total
            update_data["manually_adjusted"] = False
            update_data["price_note"] = None

        else:
            # ✅ Self-Drive Pricing (server = source of truth)
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

            # New terms → engine truth
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

    # ✅ SAFETY: Remove legacy transfer-specific add-ons from Booking update payload.
    # These belong to the AirportTransfer extension model, not the core Booking model.
    # Note: 'service_details' is a valid JSON column on Booking, so we DO NOT pop it.
    update_data.pop("toll_fees", None)
    update_data.pop("parking_fees", None)

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
        print(f"️ Warning: Failed to log booking update: {e}")

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
