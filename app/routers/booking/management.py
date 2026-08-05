from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.dependencies.tenant import TenantScope, get_tenant_scope
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingCreate, BookingOut, BookingUpdate
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_booking_list, set_cached_booking_list, invalidate_booking_cache
from app.services.booking_tasks import BookingTaskService
from app.services.number_generator import generate_booking_number  # ✅ NEW: Centralized number generator
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
    # Check cache first
    cached = await get_cached_booking_list(
        scope.tenant_id,
        archived=False, 
        vehicle_id=vehicle_id, 
        client_id=client_id
    )
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)
    
    # Cache miss: fetch from DB
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
    
    # Write to cache (5-minute TTL)
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
    # Check cache first
    cached = await get_cached_booking_list(scope.tenant_id, archived=True)
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)
    
    # Cache miss: fetch from DB
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle)
    ).where(Booking.is_archived == True)
    if scope.tenant_id is not None:
        stmt = stmt.where(Booking.tenant_id == scope.tenant_id)
    stmt = stmt.order_by(Booking.archived_at.desc())
    
    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()
    
    # Write to cache
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
# CREATE
# ---------------------------------------------------------------------------

@router.post("/", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_booking(
    request: Request,
    booking: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),  # ✅ Require active subscription
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

    # ✅ DOUBLE BOOKING PREVENTION (Overlap Check for Creation)
    overlap_stmt = select(Booking).where(
        Booking.vehicle_id == booking.vehicle_id,
        Booking.tenant_id == current_user.tenant_id,
        Booking.is_archived == False,
        Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed, BookingStatus.active]),
        and_(
            Booking.start_date < booking.end_date,
            Booking.end_date > booking.start_date
        )
    )
    overlap_result = await db.execute(overlap_stmt)
    if overlap_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail=f"Vehicle {vehicle.plate_number} is already booked for these dates."
        )

    # 3. ✅ Generate Booking Number (Centralized, tenant-scoped, monthly-resetting)
    # Format: B{YYYY}{MM}{###} (e.g., B202607001)
    new_booking_number = await generate_booking_number(db, current_user.tenant_id)

    # 4. Create Booking
    db_booking = Booking(
        **booking.model_dump(),
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
    
    # ✅ Invalidate cache
    await invalidate_booking_cache(current_user.tenant_id)
    
    # ✅ Re-fetch the booking with relationships eagerly loaded for Pydantic serialization
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
    
    # ✅ DOUBLE BOOKING PREVENTION (Overlap Check for Updates)
    # Only run if the user is changing the dates
    if 'start_date' in update_data or 'end_date' in update_data:
        target_start_date = update_data.get('start_date', booking.start_date)
        target_end_date = update_data.get('end_date', booking.end_date)
        
        overlap_stmt = select(Booking).where(
            Booking.vehicle_id == booking.vehicle_id,
            Booking.tenant_id == current_user.tenant_id,
            Booking.is_archived == False,
            Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed, BookingStatus.active]),
            Booking.id != booking.id,  # Exclude the current booking from the check
            and_(
                Booking.start_date < target_end_date,
                Booking.end_date > target_start_date
            )
        )
        overlap_result = await db.execute(overlap_stmt)
        if overlap_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="This vehicle is already booked for the selected dates."
            )

    for field, value in update_data.items():
        setattr(booking, field, value)
        
    await db.commit()
    await db.refresh(booking)
    
    # ✅ Invalidate cache
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
    
    # ✅ Invalidate cache
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
    
    # ✅ Invalidate cache
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
    
    # ✅ Invalidate cache
    await invalidate_booking_cache(current_user.tenant_id)
