# app/routers/bookings/management.py
from datetime import datetime, timezone
from decimal import Decimal
import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.commission_lock import require_not_commission_locked
from app.dependencies.subscription import require_active_subscription
from app.dependencies.tenant import TenantScope, get_tenant_scope
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingCreate, BookingOut, BookingUpdate, BookingQuote
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_booking_list, set_cached_booking_list, invalidate_booking_cache
from app.services.booking_tasks import BookingTaskService
from app.services.number_generator import generate_booking_number
from app.services.pricing import (
    SELFDRIVE, calculate, get_pricing_config, snapshot_fields,
)
from ._helpers import get_authorized_booking_async

router = APIRouter()


# ---------------------------------------------------------------------------
# READ (Tenant-Scoped Caching for Lists & Gantt Chart)
# ---------------------------------------------------------------------------

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
        return paginate_cached_items(cached, page=page, page_size=page_size)
    
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle)
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
    
    await set_cached_booking_list(
        scope.tenant_id,
        archived=False, 
        vehicle_id=vehicle_id, 
        client_id=client_id,
        bookings=bookings
    )
    
    return paginate_items(bookings, total=len(bookings), page=page, page_size=page_size)


@router.get("/archived", response_model=PaginatedResponse[BookingOut])
async def list_archived_bookings(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TenantScope = Depends(get_tenant_scope),
):
    """
    ✅ SECURITY: Manual tenant-scoped caching.
    """
    cached = await get_cached_booking_list(scope.tenant_id, archived=True)
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)
    
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle)
    ).where(Booking.is_archived == True)
    if scope.tenant_id is not None:
        stmt = stmt.where(Booking.tenant_id == scope.tenant_id)
    stmt = stmt.order_by(Booking.archived_at.desc())
    
    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()
    
    await set_cached_booking_list(scope.tenant_id, archived=True, bookings=bookings)
    
    return paginate_items(bookings, total=len(bookings), page=page, page_size=page_size)


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Single booking lookup. Not cached (low frequency, high security risk if cached incorrectly).
    The helper enforces tenant isolation.
    """
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.invoices)
    ).where(Booking.id == booking.id)
    result = await db.execute(stmt)
    booking = result.scalars().unique().first()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    return booking


# ---------------------------------------------------------------------------
# ✅ MILESTONE 1: LIVE PRICING QUOTE (no DB writes — powers frontend preview)
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

    daily_rate = Decimal(vehicle.daily_rate or 0)
    if daily_rate <= 0:
        raise HTTPException(status_code=400, detail="Vehicle has no daily rate configured.")

    config = await get_pricing_config(db, current_user.tenant_id, quote.service_type)
    try:
        result = calculate(
            service_type=quote.service_type,
            pickup_at=quote.pickup_at,
            return_at=quote.return_at,
            daily_rate=daily_rate,
            day_hours=config.day_hours if config else None,
            grace_minutes=config.grace_minutes if config else None,
            overtime_hourly_rate=config.overtime_hourly_rate if config else None,
            cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return dataclasses.asdict(result)


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found."
        )
    if client.status == ClientStatus.suspended or client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client cannot make bookings."
        )

    # 2. Validate Vehicle
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id,
    )
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found."
        )
    if vehicle.status != VehicleStatus.available or vehicle.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle is not available."
        )

    # ✅ MILESTONE 1: Resolve exact schedule (times → dates fallback)
    service_type = getattr(booking, "service_type", None) or SELFDRIVE
    pickup_at = getattr(booking, "pickup_at", None) or booking.start_date
    scheduled_return_at = getattr(booking, "scheduled_return_at", None) or booking.end_date

    # ✅ DOUBLE BOOKING PREVENTION (now time-exact; coalesce covers pre-migration rows)
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
            status_code=status.HTTP_409_CONFLICT, 
            detail=f"Vehicle {vehicle.plate_number} is already booked for these dates."
        )

    # ✅ MILESTONE 1: Server-side pricing (source of truth — client totals ignored)
    daily_rate = Decimal(vehicle.daily_rate or getattr(booking, "daily_rate", None) or 0)
    if daily_rate <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle has no daily rate configured.",
        )

    config = await get_pricing_config(db, current_user.tenant_id, service_type)
    try:
        quote = calculate(
            service_type=service_type,
            pickup_at=pickup_at,
            return_at=scheduled_return_at,
            daily_rate=daily_rate,
            day_hours=config.day_hours if config else None,
            grace_minutes=config.grace_minutes if config else None,
            overtime_hourly_rate=config.overtime_hourly_rate if config else None,
            cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. ✅ Generate Booking Number (Centralized, tenant-scoped, monthly-resetting)
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
    
    # 5. Generate Tasks (Wrapped in try-except so it doesn't block booking creation)
    try:
        await BookingTaskService.on_booking_created(db, db_booking, client.full_name, vehicle.plate_number)
    except Exception as e:
        print(f"⚠️ Warning: Failed to create tasks for booking {db_booking.id}: {e}")
    
    await invalidate_booking_cache(current_user.tenant_id)
    
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle)
    ).where(Booking.id == db_booking.id)
    
    result = await db.execute(stmt)
    return result.scalars().first()


# ---------------------------------------------------------------------------
# UPDATE / ARCHIVE / RESTORE / DELETE
# ---------------------------------------------------------------------------

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

    # ✅ MILESTONE 1: effective post-update schedule (times → dates fallback)
    target_service = update_data.get("service_type", booking.service_type) or SELFDRIVE
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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="This vehicle is already booked for the selected dates.",
            )

        # ✅ Re-price on schedule change (server remains source of truth)
        vehicle_stmt = select(Vehicle).where(Vehicle.id == booking.vehicle_id)
        vehicle = (await db.execute(vehicle_stmt)).scalars().first()
        daily_rate = Decimal(vehicle.daily_rate or booking.daily_rate or 0)
        if daily_rate > 0:
            config = await get_pricing_config(db, current_user.tenant_id, target_service)
            try:
                quote = calculate(
                    service_type=target_service,
                    pickup_at=target_pickup,
                    return_at=target_return,
                    daily_rate=daily_rate,
                    day_hours=config.day_hours if config else None,
                    grace_minutes=config.grace_minutes if config else None,
                    overtime_hourly_rate=config.overtime_hourly_rate if config else None,
                    cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active bookings cannot be archived"
        )
    if booking.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is already archived"
        )
    
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is not archived"
        )
    
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active bookings cannot be deleted."
        )
    
    try:
        await db.delete(booking)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete booking with invoices or contracts. Please archive instead."
        )
    
    await invalidate_booking_cache(current_user.tenant_id)
