"""READ + QUOTE — tenant-scoped cached lists, single lookup, live pricing quote."""
import dataclasses
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import TenantScope, get_tenant_scope
from app.models.bookings import Booking
from app.models.drivers import Driver
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.booking import BookingOut, BookingQuote
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_booking_list, set_cached_booking_list
from app.services.pricing_selfdrive import quote_selfdrive  # ✅ PHASE 1: pure engine
from app.services.pricing_airport import quote_airport_transfer  # ✅ MILESTONE 2: pure engine
from app.services.pricing_wedding import quote_wedding  # ✅ MILESTONE 3: pure engine
from app.services.pricing_prodriver import quote_prodriver  # ✅ MILESTONE 3: pure engine
from ._helpers import get_authorized_booking_async

router = APIRouter()

SELFDRIVE = "selfdrive"
AIRPORT_TRANSFER = "airport_transfer"
WEDDING = "wedding"
PRO_DRIVER = "pro_driver"


# ✅ NEW: Helper to safely convert Booking → BookingOut with denormalized UI fields
def serialize_booking(booking: Booking) -> BookingOut:
    """Manually populate denormalized UI fields.

    ✅ INVARIANT: call only on eager-loaded bookings (all call sites here do).
    ✅ Flat fields read from __dict__ — never trigger lazy-load even if the
    invariant is ever broken (MissingGreenlet-proof for the denormalized part).
    """
    data = BookingOut.model_validate(booking)  # Base serialization (nested objects)

    # ✅ Safe in-memory reads (no lazy-load on these fields)
    client = booking.__dict__.get("client")
    vehicle = booking.__dict__.get("vehicle")

    data.client_name = client.full_name if client else None
    data.client_phone = client.phone if client else None
    data.vehicle_plate = vehicle.plate_number if vehicle else None
    data.vehicle_name = f"{vehicle.make} {vehicle.model}" if vehicle else None

    return data


@router.get("/", response_model=PaginatedResponse[BookingOut])
async def list_bookings(
    request: Request,
    vehicle_id: int = Query(None),
    client_id: int = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TenantScope = Depends(get_tenant_scope),
):
    """
    ✅ SECURITY: Manual tenant-scoped caching.
    Default @cache decorator does NOT include tenant context, causing cross-tenant leaks.
    """
    cached = await get_cached_booking_list(
        scope.tenant_id,
        archived=False,
        vehicle_id=vehicle_id,
        client_id=client_id
    )
    if cached is not None:
        # ✅ Return cached items (already serialized as dicts)
        return paginate_cached_items(cached, page=page, page_size=page_size)

    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver)  # ✅ MILESTONE 2: eager-load driver (avoids async lazy-load)
    ).where(Booking.is_archived == False)
    if scope.tenant_id is not None:
        stmt = stmt.where(Booking.tenant_id == scope.tenant_id)
    if vehicle_id is not None:
        stmt = stmt.where(Booking.vehicle_id == vehicle_id)
    if client_id is not None:
        stmt = stmt.where(Booking.client_id == client_id)

    stmt = stmt.order_by(Booking.created_at.desc())
    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()

    # ✅ NEW: Serialize with denormalized UI fields before caching
    serialized_bookings = [serialize_booking(b) for b in bookings]

    await set_cached_booking_list(
        scope.tenant_id,
        archived=False,
        vehicle_id=vehicle_id,
        client_id=client_id,
        bookings=serialized_bookings  # ✅ Cache the serialized versions
    )

    return paginate_items(serialized_bookings, total=len(serialized_bookings), page=page, page_size=page_size)


@router.get("/archived", response_model=PaginatedResponse[BookingOut])
async def list_archived_bookings(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TenantScope = Depends(get_tenant_scope),
):
    """✅ SECURITY: Manual tenant-scoped caching."""
    cached = await get_cached_booking_list(scope.tenant_id, archived=True)
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver)  # ✅ MILESTONE 2
    ).where(Booking.is_archived == True)
    if scope.tenant_id is not None:
        stmt = stmt.where(Booking.tenant_id == scope.tenant_id)
    stmt = stmt.order_by(Booking.archived_at.desc())

    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()

    # ✅ NEW: Serialize with denormalized UI fields before caching
    serialized_bookings = [serialize_booking(b) for b in bookings]

    await set_cached_booking_list(scope.tenant_id, archived=True, bookings=serialized_bookings)

    return paginate_items(serialized_bookings, total=len(serialized_bookings), page=page, page_size=page_size)


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single booking lookup. Not cached. Helper enforces tenant isolation."""
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.invoices),
        selectinload(Booking.driver)  # ✅ MILESTONE 2: powers DriverProfileWidget
    ).where(Booking.id == booking.id)
    result = await db.execute(stmt)
    booking = result.scalars().unique().first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # ✅ NEW: Return serialized with denormalized UI fields
    return serialize_booking(booking)


# ---------------------------------------------------------------------------
# ✅ MILESTONE 2 & 3: LIVE PRICING QUOTE (Pricing Factory)
# Dispatches to the correct pure engine based on service_type.
# ---------------------------------------------------------------------------

@router.post("/quote", response_model=dict)
@limiter.limit("30/minute")
async def quote_booking(
    request: Request,
    quote: BookingQuote,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == quote.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id,
    )
    vehicle = (await db.execute(vehicle_stmt)).scalars().first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    # ✅ MILESTONE 2: Service type detection (safe fallback to selfdrive)
    service_type = getattr(quote, "service_type", None) or SELFDRIVE

    if service_type == AIRPORT_TRANSFER:
        # Validate vehicle supports airport transfer
        if not vehicle.supports_airport_transfer or not vehicle.airport_transfer_base_rate:
            raise HTTPException(
                status_code=400,
                detail="Vehicle does not support airport transfers or has no base rate configured."
            )
        
        # Extract optional add-ons (safe fallback if not in schema yet)
        toll_fees = getattr(quote, "toll_fees", 0) or 0
        parking_fees = getattr(quote, "parking_fees", 0) or 0

        try:
            result = quote_airport_transfer(
                base_rate=Decimal(vehicle.airport_transfer_base_rate),
                toll_fees=Decimal(toll_fees),
                parking_fees=Decimal(parking_fees),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    elif service_type == WEDDING:
        # Validate vehicle supports wedding service
        if not vehicle.supports_wedding_service or not vehicle.wedding_base_rate:
            raise HTTPException(
                status_code=400,
                detail="Vehicle does not support wedding services or has no base rate configured."
            )
        
        # Extract service-specific details from JSON payload
        details = getattr(quote, "service_details", None) or {}
        extra_hours = int(details.get("extra_hours", 0))
        toll_fees = details.get("toll_fees", 0)
        decoration_fee = details.get("decoration_fee", 0)
        priority_booking_fee = details.get("priority_booking_fee", 0)
        fuel_fee = details.get("fuel_fee", 0)

        # Overtime rate: use assigned driver's fee if provided, else fallback to 0
        overtime_rate = 0
        if quote.driver_id is not None:
            driver_stmt = select(Driver).where(
                Driver.id == quote.driver_id,
                Driver.tenant_id == current_user.tenant_id,
            )
            driver = (await db.execute(driver_stmt)).scalars().first()
            if not driver:
                raise HTTPException(status_code=404, detail="Driver not found.")
            overtime_rate = driver.overtime_hourly_fee or 0

        try:
            result = quote_wedding(
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

    elif service_type == PRO_DRIVER:
        # ✅ Pro Driver requires a staff driver assignment
        if quote.driver_id is None:
            raise HTTPException(
                status_code=400,
                detail="Pro Driver (Chauffeur) service requires a staff driver assignment."
            )
        
        # Fetch driver for fees
        driver_stmt = select(Driver).where(
            Driver.id == quote.driver_id,
            Driver.tenant_id == current_user.tenant_id,
        )
        driver = (await db.execute(driver_stmt)).scalars().first()
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found.")

        # Extract service-specific details from JSON payload
        details = getattr(quote, "service_details", None) or {}
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
            result = quote_prodriver(
                base_rate=base_rate,
                overtime_hourly_rate=overtime_rate,
                extra_hours=extra_hours,
                accommodation_fee=Decimal(accommodation_fee),
                toll_fees=Decimal(toll_fees),
                parking_fees=Decimal(parking_fees),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    else:
        # ✅ PHASE 1: Self-Drive Pricing
        # per-quote rate override (vehicle row is NEVER mutated)
        daily_rate = Decimal(quote.daily_rate_override or vehicle.daily_rate or 0)
        if daily_rate <= 0:
            raise HTTPException(status_code=400, detail="Vehicle has no daily rate configured.")

        # Driver optional — adds that driver's own daily fee
        driver_daily_fee = None
        if quote.driver_id is not None:
            driver_stmt = select(Driver).where(
                Driver.id == quote.driver_id,
                Driver.tenant_id == current_user.tenant_id,
            )
            driver = (await db.execute(driver_stmt)).scalars().first()
            if not driver:
                raise HTTPException(status_code=404, detail="Driver not found.")
            driver_daily_fee = driver.daily_fee

        try:
            result = quote_selfdrive(
                pickup_at=quote.pickup_at,
                return_at=quote.return_at,
                daily_rate=daily_rate,
                driver_daily_fee=Decimal(driver_daily_fee) if driver_daily_fee else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    return dataclasses.asdict(result)
