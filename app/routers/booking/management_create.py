# app/routers/booking/management_create.py
"""CREATE — validation, double-booking prevention, server-side pricing, tasks."""
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.commission_lock import require_not_commission_locked
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.drivers import Driver, DriverStatus
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingCreate, BookingOut
from app.services.booking_tasks import BookingTaskService
from app.services.cache import invalidate_booking_cache
from app.services.number_generator import generate_booking_number
from app.services.pricing import SELFDRIVE, calculate, get_pricing_config, resolve_driver_fees, snapshot_fields

router = APIRouter()


async def validate_driver_assignment(
    db: AsyncSession, tenant_id: int, driver_id: int,
) -> Driver:
    """
    ✅ MILESTONE 2 SECURITY: driver must exist, belong to THIS tenant,
    not be archived, and not be suspended. Shared with lifecycle next.
    """
    stmt = select(Driver).where(
        Driver.id == driver_id,
        Driver.tenant_id == tenant_id,
    )
    driver = (await db.execute(stmt)).scalars().first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found.",
        )
    if driver.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver is archived and cannot be assigned.",
        )
    if driver.status == DriverStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver is suspended and cannot be assigned.",
        )
    return driver


@router.post("/", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_booking(
    request: Request,
    booking: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    # 1. Validate Client
    client_stmt = select(Client).where(
        Client.id == booking.client_id,
        Client.tenant_id == current_user.tenant_id,
    )
    client_result = await db.execute(client_stmt)
    client = client_result.scalars().first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    if client.status == ClientStatus.suspended or client.is_archived:
        raise HTTPException(status_code=400, detail="Client cannot make bookings.")

    # 2. Validate Vehicle
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id,
    )
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalars().first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if vehicle.status != VehicleStatus.available or vehicle.is_archived:
        raise HTTPException(status_code=409, detail="Vehicle is not available.")

    # ✅ MILESTONE 1: Resolve exact schedule (times → dates fallback)
    service_type = getattr(booking, "service_type", None) or SELFDRIVE
    pickup_at = getattr(booking, "pickup_at", None) or booking.start_date
    scheduled_return_at = getattr(booking, "scheduled_return_at", None) or booking.end_date

    # ✅ PAST-TIME GUARD: new bookings cannot be scheduled in the past.
    # 2-minute buffer accounts for clock skew between client and server.
    now_naive = datetime.utcnow()
    pickup_naive = pickup_at.replace(tzinfo=None) if pickup_at.tzinfo else pickup_at
    if pickup_naive < (now_naive - timedelta(minutes=2)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pickup time cannot be in the past. Please select a future date and time.",
        )

    # ✅ MILESTONE 2: Service-driver compatibility guard
    if service_type == SELFDRIVE and booking.driver_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Self-drive bookings cannot have an assigned driver. The client drives.",
        )

    # ✅ MILESTONE 2: Validate Driver (tenant-scoped, eligibility-checked)
    # Captures the driver object for fee resolution (zero extra queries later)
    driver = None
    if booking.driver_id is not None:
        driver = await validate_driver_assignment(db, current_user.tenant_id, booking.driver_id)

    # ✅ DOUBLE BOOKING PREVENTION (time-exact; coalesce covers pre-migration rows)
    overlap_stmt = select(Booking).where(
        Booking.vehicle_id == booking.vehicle_id,
        Booking.tenant_id == current_user.tenant_id,
        Booking.is_archived == False,
        Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed, BookingStatus.active]),
        and_(
            func.coalesce(Booking.pickup_at, Booking.start_date) < scheduled_return_at,
            func.coalesce(Booking.scheduled_return_at, Booking.end_date) > pickup_at,
        )
    )
    overlap_result = await db.execute(overlap_stmt)
    if overlap_result.scalars().first():
        raise HTTPException(
            status_code=409,
            detail=f"Vehicle {vehicle.plate_number} is already booked for these dates."
        )

    # ✅ MILESTONE 1: Server-side pricing (source of truth — client totals ignored)
    daily_rate = Decimal(vehicle.daily_rate or getattr(booking, "daily_rate", None) or 0)
    if daily_rate <= 0:
        raise HTTPException(status_code=400, detail="Vehicle has no daily rate configured.")

    config = await get_pricing_config(db, current_user.tenant_id, service_type)
    
    # ✅ MILESTONE 2: Resolve driver fees (per-driver → config → None)
    driver_fees = resolve_driver_fees(driver, config)
    
    try:
        quote = calculate(
            service_type=service_type,
            pickup_at=pickup_at,
            return_at=scheduled_return_at,
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
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. ✅ Generate Booking Number (tenant-scoped, monthly-resetting)
    new_booking_number = await generate_booking_number(db, current_user.tenant_id)

    # 4. Create Booking (with pricing snapshot — contracts never mutate)
    payload = booking.model_dump()
    payload.update({
        "service_type": service_type,
        "pickup_at": pickup_at,
        "scheduled_return_at": scheduled_return_at,
        "daily_rate": daily_rate,
        "total_amount": quote.total,
        **snapshot_fields(config, service_type),
    })

    db_booking = Booking(
        **payload,
        tenant_id=current_user.tenant_id,
        status=BookingStatus.pending,
        booking_number=new_booking_number,
    )
    db.add(db_booking)
    await db.commit()
    await db.refresh(db_booking)

    # 5. Generate Tasks (non-blocking)
    try:
        await BookingTaskService.on_booking_created(db, db_booking, client.full_name, vehicle.plate_number)
    except Exception as e:
        print(f"⚠️ Warning: Failed to create tasks for booking {db_booking.id}: {e}")

    await invalidate_booking_cache(current_user.tenant_id)

    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver)
    ).where(Booking.id == db_booking.id)

    result = await db.execute(stmt)
    return result.scalars().first()
