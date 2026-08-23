# app/routers/booking/management_lifecycle.py
"""UPDATE / ARCHIVE / RESTORE / DELETE — post-creation lifecycle."""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking, BookingStatus
from app.models.drivers import Driver
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.booking import BookingOut, BookingUpdate
from app.services.cache import invalidate_booking_cache
from app.services.pricing import SELFDRIVE, calculate, get_pricing_config, resolve_driver_fees, snapshot_fields
from ._helpers import get_authorized_booking_async
from .management_create import validate_driver_assignment

router = APIRouter()


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

    # ✅ MILESTONE 2: Service-driver compatibility guard (covers both create-time and reassign)
    target_service = update_data.get("service_type", booking.service_type) or SELFDRIVE
    target_driver_id = update_data.get("driver_id", booking.driver_id)

    if target_service == SELFDRIVE and target_driver_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Self-drive bookings cannot have an assigned driver. The client drives.",
        )

    # ✅ MILESTONE 2: Validate driver on reassign; allow null to unassign
    # Captures the driver object for fee resolution below
    target_driver = booking.driver  # already eager-loaded by helper
    if "driver_id" in update_data and update_data["driver_id"] is not None:
        target_driver = await validate_driver_assignment(
            db, current_user.tenant_id, update_data["driver_id"]
        )
    elif "driver_id" in update_data and update_data["driver_id"] is None:
        # Explicit null = unassign
        target_driver = None

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

        # ✅ Re-price on schedule change (server remains source of truth)
        vehicle_stmt = select(Vehicle).where(Vehicle.id == booking.vehicle_id)
        vehicle = (await db.execute(vehicle_stmt)).scalars().first()
        daily_rate = Decimal(vehicle.daily_rate or booking.daily_rate or 0)
        if daily_rate > 0:
            config = await get_pricing_config(db, current_user.tenant_id, target_service)
            
            # ✅ MILESTONE 2: Resolve driver fees for the target driver (new or existing)
            driver_fees = resolve_driver_fees(target_driver, config)
            
            try:
                quote = calculate(
                    service_type=target_service,
                    pickup_at=target_pickup,
                    return_at=target_return,
                    daily_rate=daily_rate,
                    billing_model=config.billing_model if config else None,
                    day_hours=config.day_hours if config else None,
                    grace_minutes=config.grace_minutes if config else None,
                    overtime_hourly_rate=config.overtime_hourly_rate if config else None,
                    cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
                    driver_daily_fee=driver_fees["driver_daily_fee"],
                    driver_overtime_hourly_fee=driver_fees["driver_overtime_hourly_fee"],
                    driver_night_accommodation_fee=driver_fees["driver_night_accommodation_fee"],
                    rate_extras=config.rate_extras if config else None,
                )
                update_data["total_amount"] = quote.total
                update_data["daily_rate"] = daily_rate
                update_data.update(snapshot_fields(config, target_service))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

    for field, value in update_data.items():
        setattr(booking, field, value)

    await db.commit()
    await db.refresh(booking)

    await invalidate_booking_cache(current_user.tenant_id)

    return booking


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
    await db.refresh(booking)

    await invalidate_booking_cache(current_user.tenant_id)

    return booking


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
    await db.refresh(booking)

    await invalidate_booking_cache(current_user.tenant_id)

    return booking


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
