from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.dependencies.commission_lock import require_not_commission_locked
from app.dependencies.tenant import TenantScope, get_tenant_scope, require_mutation_tenant_scope
from app.models.bookings import Booking, BookingStatus
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.vehicle import VehicleCreate, VehicleOut, VehicleUpdate
from app.services.cache import get_cached_vehicle_list, set_cached_vehicle_list, invalidate_vehicle_cache
from app.services.vehicle_tasks import VehicleTaskService
from ._helpers import get_authorized_vehicle_async

router = APIRouter()


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

@router.post("/", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_vehicle(
    request: Request,
    vehicle: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    data = vehicle.model_dump()
    data["status"] = VehicleStatus.pending_activation
    
    db_vehicle = Vehicle(**data, tenant_id=scope.tenant_id)
    db.add(db_vehicle)
    await db.commit()
    await db.refresh(db_vehicle)
    
    # Trigger lifecycle tasks
    await VehicleTaskService.on_vehicle_created(db, db_vehicle, db_vehicle.tenant_id)
    await VehicleTaskService.dispatch_lifecycle_tasks(db, db_vehicle, "created")
    
    # ✅ CRITICAL: Invalidate cache so new vehicle appears immediately
    await invalidate_vehicle_cache(db_vehicle.tenant_id)
    
    return db_vehicle


# ---------------------------------------------------------------------------
# READ (Tenant-Scoped Caching for Gantt Chart & Lists)
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[VehicleOut])
async def read_vehicles(
    request: Request,
    status_filter: VehicleStatus | None = None,
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
    cached = await get_cached_vehicle_list(scope.tenant_id, archived=False, status_filter=status_filter)
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)
    
    # Cache miss: fetch from DB
    stmt = select(Vehicle).where(Vehicle.is_archived == False)
    if scope.tenant_id is not None:
        stmt = stmt.where(Vehicle.tenant_id == scope.tenant_id)
    if status_filter:
        stmt = stmt.where(Vehicle.status == status_filter)
        
    result = await db.execute(stmt)
    vehicles = result.scalars().all()
    
    # Write to cache (5-minute TTL)
    await set_cached_vehicle_list(scope.tenant_id, archived=False, status_filter=status_filter, vehicles=vehicles)
    
    return paginate_items(vehicles, total=len(vehicles), page=page, page_size=page_size)


@router.get("/archived", response_model=PaginatedResponse[VehicleOut])
async def read_archived_vehicles(
    request: Request,
    status_filter: VehicleStatus | None = None,
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
    cached = await get_cached_vehicle_list(scope.tenant_id, archived=True, status_filter=status_filter)
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)
    
    # Cache miss: fetch from DB
    stmt = select(Vehicle).where(Vehicle.is_archived == True)
    if scope.tenant_id is not None:
        stmt = stmt.where(Vehicle.tenant_id == scope.tenant_id)
    if status_filter:
        stmt = stmt.where(Vehicle.status == status_filter)
        
    result = await db.execute(stmt)
    vehicles = result.scalars().all()
    
    # Write to cache
    await set_cached_vehicle_list(scope.tenant_id, archived=True, status_filter=status_filter, vehicles=vehicles)
    
    return paginate_items(vehicles, total=len(vehicles), page=page, page_size=page_size)


@router.get("/{vehicle_id}", response_model=VehicleOut)
async def read_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Single vehicle lookup. Not cached (low frequency, high security risk if cached incorrectly).
    The helper enforces tenant isolation.
    """
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    return vehicle


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

@router.patch("/{vehicle_id}", response_model=VehicleOut)
@limiter.limit("30/minute")
async def update_vehicle(
    request: Request,
    vehicle_id: int,
    updates: VehicleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)

    update_data = updates.model_dump(exclude_unset=True)
    
    # ✅ SIMPLIFIED: Only validate that insurance is not expired
    if "insurance_expiry" in update_data:
        new_expiry = update_data["insurance_expiry"]
        if new_expiry <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insurance expiry cannot be set to a past date."
            )
            
    for field, value in update_data.items():
        setattr(vehicle, field, value)
        
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
        
    return vehicle


# ---------------------------------------------------------------------------
# ARCHIVE / RESTORE / DELETE
# ---------------------------------------------------------------------------

@router.post("/{vehicle_id}/archive", response_model=VehicleOut)
@limiter.limit("10/minute")
async def archive_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot archive a vehicle that is currently rented."
        )
    if vehicle.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is already archived."
        )
    
    # ✅ Check for active bookings
    active_bookings_stmt = select(Booking).where(
        Booking.vehicle_id == vehicle.id,
        Booking.status.in_([BookingStatus.confirmed, BookingStatus.ongoing])
    )
    active_bookings = (await db.execute(active_bookings_stmt)).scalars().first()
    if active_bookings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot archive vehicle with active bookings. Please complete or cancel bookings first."
        )
        
    vehicle.is_archived = True
    vehicle.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle


@router.post("/{vehicle_id}/restore", response_model=VehicleOut)
@limiter.limit("10/minute")
async def restore_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if not vehicle.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is not archived."
        )
        
    vehicle.is_archived = False
    vehicle.archived_at = None
    vehicle.status = VehicleStatus.available
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a vehicle that is currently rented."
        )
    
    # ✅ Check for active bookings
    active_bookings_stmt = select(Booking).where(
        Booking.vehicle_id == vehicle.id,
        Booking.status.in_([BookingStatus.confirmed, BookingStatus.ongoing])
    )
    active_bookings = (await db.execute(active_bookings_stmt)).scalars().first()
    if active_bookings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete vehicle with active bookings. Please complete or cancel bookings first."
        )
        
    try:
        await db.delete(vehicle)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete vehicle with historical bookings. Please archive it instead."
        )
    
    # ✅ Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
