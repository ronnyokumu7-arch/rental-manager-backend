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
from app.services.pricing_selfdrive import quote_selfdrive  # ✅ PHASE 1: pure pricing engine
from app.services.activity_logs.booking import BookingActivityLogger
from app.services.activity_logs.client import ClientActivityLogger

router = APIRouter()

SELFDRIVE = "selfdrive"


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

    # ✅ Resolve exact schedule (times → dates fallback)
    service_type = getattr(booking, "service_type", None) or SELFDRIVE
    pickup_at = getattr(booking, "pickup_at", None) or booking.start_date
    scheduled_return_at = getattr(booking, "scheduled_return_at", None) or booking.end_date

    # ✅ PAST-TIME GUARD: new bookings cannot be scheduled in the past.
    now_naive = datetime.utcnow()
    pickup_naive = pickup_at.replace(tzinfo=None) if pickup_at.tzinfo else pickup_at
    if pickup_naive < (now_naive - timedelta(minutes=2)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pickup time cannot be in the past. Please select a future date and time.",
        )

    # ✅ PHASE 1: Driver optional for self-drive (old 422 guard removed)
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

    # ✅ PHASE 1: Self-Drive Pricing (pure calculation — server is source of truth)
    daily_rate = booking.daily_rate or vehicle.daily_rate
    if not daily_rate or daily_rate <= 0:
        raise HTTPException(status_code=400, detail="Vehicle has no daily rate configured.")

    driver_daily_fee = driver.daily_fee if driver else None

    try:
        quote = quote_selfdrive(
            pickup_at=pickup_at,
            return_at=scheduled_return_at,
            daily_rate=Decimal(daily_rate),
            driver_daily_fee=Decimal(driver_daily_fee) if driver_daily_fee else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. ✅ Generate Booking Number (tenant-scoped, monthly-resetting)
    new_booking_number = await generate_booking_number(db, current_user.tenant_id)

    # 4. Create Booking (with Phase 1 pricing snapshot — contracts never mutate)
    payload = booking.model_dump()
    payload.update({
        "service_type": service_type,
        "pickup_at": pickup_at,
        "scheduled_return_at": scheduled_return_at,
        "daily_rate": daily_rate,
        "billable_days": quote.billable_days,
        "computed_total": quote.total,
        "total_amount": quote.total,
        "manually_adjusted": False,
        "price_note": None,
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

    # ✅ Log the booking created event to the Activity Feed
    try:
        await BookingActivityLogger.on_created(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            booking=db_booking,
            client_name=client.full_name,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log booking creation: {e}")

    # ✅ Log the client event (if first booking, optional)
    try:
        await ClientActivityLogger.on_created(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            client=client,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log client creation: {e}")

    await invalidate_booking_cache(current_user.tenant_id)

    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver)
    ).where(Booking.id == db_booking.id)

    result = await db.execute(stmt)
    return result.scalars().first()
