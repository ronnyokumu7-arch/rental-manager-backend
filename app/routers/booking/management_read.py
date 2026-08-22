# app/routers/booking/management_read.py
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
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.booking import BookingOut, BookingQuote
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_booking_list, set_cached_booking_list
from app.services.pricing import SELFDRIVE, calculate, get_pricing_config
from ._helpers import get_authorized_booking_async

router = APIRouter()


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
    """✅ SECURITY: Manual tenant-scoped caching."""
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
    """Single booking lookup. Not cached. Helper enforces tenant isolation."""
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.invoices)
    ).where(Booking.id == booking.id)
    result = await db.execute(stmt)
    booking = result.scalars().unique().first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
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
            billing_model=config.billing_model if config else None,
            day_hours=config.day_hours if config else None,
            grace_minutes=config.grace_minutes if config else None,
            overtime_hourly_rate=config.overtime_hourly_rate if config else None,
            cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
            rate_extras=config.rate_extras if config else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return dataclasses.asdict(result)
