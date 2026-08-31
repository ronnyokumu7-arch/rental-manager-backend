"""CREATE — validation, double-booking prevention, server-side pricing, tasks.

✅ QUOTATION PIPELINE: every booking is born together with its quotation
(doc_type=quotation, status=sent, share_token ready) in ONE atomic commit.
Client accepts on the public page → morph to invoice + pending→confirmed.
"""
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
from app.services.invoices import create_quotation_for_booking  # ✅ QUOTATION PIPELINE
from app.services.pricing_selfdrive import quote_selfdrive  # ✅ PHASE 1: pure pricing engine
from app.services.pricing_airport import quote_airport_transfer  # ✅ MILESTONE 2: pure pricing engine
from app.services.pricing_wedding import quote_wedding  # ✅ MILESTONE 3: pure pricing engine
from app.services.pricing_prodriver import quote_prodriver  # ✅ MILESTONE 3: pure pricing engine
from app.services.activity_logs.booking import BookingActivityLogger
from app.services.activity_logs.client import ClientActivityLogger

router = APIRouter()

SELFDRIVE = "selfdrive"
AIRPORT_TRANSFER = "airport_transfer"
WEDDING = "wedding"
PRO_DRIVER = "pro_driver"


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

    # ✅ MILESTONE 2 & 3: PRICING FACTORY (Dispatches to correct pure engine)
    daily_rate = None
    billable_days = None
    computed_total = None

    if service_type == AIRPORT_TRANSFER:
        # Validate vehicle supports airport transfer
        if not vehicle.supports_airport_transfer or not vehicle.airport_transfer_base_rate:
            raise HTTPException(
                status_code=400,
                detail="Vehicle does not support airport transfers or has no base rate configured."
            )
        
        # Extract optional add-ons (safe fallback if not in schema yet)
        toll_fees = getattr(booking, "toll_fees", None) or 0
        parking_fees = getattr(booking, "parking_fees", None) or 0

        try:
            quote = quote_airport_transfer(
                base_rate=Decimal(vehicle.airport_transfer_base_rate),
                toll_fees=Decimal(toll_fees),
                parking_fees=Decimal(parking_fees),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        daily_rate = vehicle.airport_transfer_base_rate
        billable_days = 1  # Airport transfers are per-trip
        computed_total = quote.total

    elif service_type == WEDDING:
        # Validate vehicle supports wedding service
        if not vehicle.supports_wedding_service or not vehicle.wedding_base_rate:
            raise HTTPException(
                status_code=400,
                detail="Vehicle does not support wedding services or has no base rate configured."
            )
        
        # Extract service-specific details from JSON payload
        details = getattr(booking, "service_details", None) or {}
        extra_hours = int(details.get("extra_hours", 0))
        toll_fees = details.get("toll_fees", 0)
        decoration_fee = details.get("decoration_fee", 0)
        priority_booking_fee = details.get("priority_booking_fee", 0)
        fuel_fee = details.get("fuel_fee", 0)

        # Overtime rate: use assigned driver's fee, else fallback to 0
        overtime_rate = driver.overtime_hourly_fee if driver and driver.overtime_hourly_fee else 0

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

        daily_rate = vehicle.wedding_base_rate
        billable_days = 1  # Wedding is a 12H package (1 day)
        computed_total = quote.total

    elif service_type == PRO_DRIVER:
        # ✅ Pro Driver requires a staff driver assignment
        if not driver:
            raise HTTPException(
                status_code=400,
                detail="Pro Driver (Chauffeur) service requires a staff driver assignment."
            )
        
        # Extract service-specific details from JSON payload
        details = getattr(booking, "service_details", None) or {}
        extra_hours = int(details.get("extra_hours", 0))
        accommodation_fee = details.get("accommodation_fee", 0)
        toll_fees = details.get("toll_fees", 0)
        parking_fees = details.get("parking_fees", 0)

        # Calculate base rate (Vehicle daily rate + Driver daily fee)
        vehicle_daily_rate = Decimal(vehicle.daily_rate) if vehicle.daily_rate else Decimal("0.00")
        driver_daily_fee = Decimal(driver.daily_fee) if driver.daily_fee else Decimal("0.00")
        base_rate = vehicle_daily_rate + driver_daily_fee

        if base_rate <= 0:
            raise HTTPException(
                status_code=400, 
                detail="Pro Driver base rate cannot be zero. Check vehicle daily rate and driver daily fee."
            )

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

        daily_rate = base_rate
        billable_days = 1  # Pro Driver is a 12H package (1 day)
        computed_total = quote.total

    else:
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

        billable_days = quote.billable_days
        computed_total = quote.total

    # 3. ✅ Generate Booking Number (tenant-scoped, monthly-resetting)
    new_booking_number = await generate_booking_number(db, current_user.tenant_id)

    # 4. Create Booking (with pricing snapshot — contracts never mutate)
    # Note: booking.model_dump() automatically includes the new service_details JSON field
    payload = booking.model_dump()
    payload.update({
        "service_type": service_type,
        "pickup_at": pickup_at,
        "scheduled_return_at": scheduled_return_at,
        "daily_rate": daily_rate,
        "billable_days": billable_days,
        "computed_total": computed_total,
        "total_amount": computed_total,
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
    await db.flush()  # ✅ assigns db_booking.id so the quotation can reference it

    # ✅ QUOTATION PIPELINE: the price offer is born WITH the booking (atomic).
    # doc_type=quotation, status=sent, share_token ready → client accepts on the
    # public page → morph to invoice + booking pending→confirmed (one commit there).
    # Idempotent + flush-only; the commit below persists booking + quotation together.
    await create_quotation_for_booking(db_booking, db)

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
            client=client,    # ✅ already loaded — safe snapshot, no lazy-load
            vehicle=vehicle,  # ✅ already loaded — safe snapshot, no lazy-load
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
        print(f"️ Warning: Failed to log client creation: {e}")

    # ✅ CRITICAL: persist the flushed activity logs + tasks.
    # The loggers flush-only; without this commit the rows roll back
    # when the session closes at request end.
    await db.commit()

    await invalidate_booking_cache(current_user.tenant_id)

    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver)
    ).where(Booking.id == db_booking.id)

    result = await db.execute(stmt)
    return result.scalars().first()
