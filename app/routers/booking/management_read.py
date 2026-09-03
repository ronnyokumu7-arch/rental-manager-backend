# app/routers/booking/management_read.py
"""
✅ READ — tenant-scoped cached lists + single booking lookup.

CONTRACT v2: pricing quotes MOVED to the booking factory
(POST /quote lives in management_create.py → booking_factory.quote_new).
This module is strictly read-only: no pricing math, no overrides, no lies.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import TenantScope, get_tenant_scope
from app.models.bookings import Booking
from app.models.users import User
from app.schemas.booking import BookingOut
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_booking_list, set_cached_booking_list
from ._helpers import get_authorized_booking_async

router = APIRouter()


# ✅ Helper to safely convert Booking → BookingOut with denormalized UI fields
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

    # ✅ Serialize with denormalized UI fields before caching
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

    # ✅ Serialize with denormalized UI fields before caching
    serialized_bookings = [serialize_booking(b) for b in bookings]

    await set_cached_booking_list(
        scope.tenant_id,
        archived=True,
        bookings=serialized_bookings
    )

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

    # ✅ Return serialized with denormalized UI fields
    return serialize_booking(booking)
