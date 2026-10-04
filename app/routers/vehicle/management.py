# app/routers/vehicle/management.py
"""
✅ VEHICLE CRUD — tenant/investor-scoped, cached lists, lifecycle tasks.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B):
  - FIXED RUNTIME BUG: BookingStatus.ongoing doesn't exist (AttributeError → 500).
    Active-booking guards now use LIVE statuses (pending|confirmed|active).
  - create: duplicate plate → typed ConflictError (was raw 500).
  - create: past insurance expiry now rejected (parity with update).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.dependencies.commission_lock import require_not_commission_locked
from app.dependencies.tenant import TenantScope, get_tenant_scope, require_mutation_tenant_scope
from app.models.bookings import Booking, BookingStatus
from app.models.users import User, UserRole
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.vehicle import VehicleCreate, VehicleOut, VehicleUpdate
from app.services.cache import get_cached_vehicle_list, set_cached_vehicle_list, invalidate_vehicle_cache
from app.services.vehicle_tasks import VehicleTaskService
from ._helpers import get_authorized_vehicle_async

router = APIRouter()

# ✅ LIVE STATUSES that block archive/delete (pending counts — quotation in flight)
ACTIVE_BLOCKING_STATUSES = [
    BookingStatus.pending,
    BookingStatus.confirmed,
    BookingStatus.active,
]


# ---------------------------------------------------------------------------
# ✅ SHARED GUARDS (Phase B)
# ---------------------------------------------------------------------------
def _assert_future_insurance(expiry) -> None:
    """Insurance expiry must be in the future (create + update parity)."""
    if expiry is not None and expiry <= datetime.now(timezone.utc):
        raise BadRequestError(
            title="Invalid Insurance Expiry",
            message="Choose a future date for the insurance expiry.",
            field_errors={"insurance_expiry": "Must be a future date"},
        )


async def _assert_no_live_bookings(db: AsyncSession, vehicle_id: int, action: str) -> None:
    """✅ FIXED: was BookingStatus.ongoing (AttributeError → 500 on every call)."""
    live_booking = (await db.execute(
        select(Booking).where(
            Booking.vehicle_id == vehicle_id,
            Booking.status.in_(ACTIVE_BLOCKING_STATUSES),
        )
    )).scalars().first()
    if live_booking:
        raise BadRequestError(
            title="Vehicle Has Active Bookings",
            message=f"This vehicle has active bookings. Complete or cancel them before {action} it.",
        )


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
    # ✅ CHANGED: Use get_tenant_scope instead of require_mutation_tenant_scope
    # This allows Investors (non-admins) to create vehicles as long as they have a tenant_id.
    scope: TenantScope = Depends(get_tenant_scope), 
):
    data = vehicle.model_dump()
    data["status"] = VehicleStatus.pending_activation

    # ✅ Phase B: reject expired insurance at creation (parity with update)
    _assert_future_insurance(data.get("insurance_expiry"))
    
    # ✅ If an investor is adding this, tag them as the owner
    owner_id = current_user.id if current_user.role.value == "investor" else None
    
    # ✅ SECURE: scope.tenant_id is guaranteed to be valid by the dependency
    db_vehicle = Vehicle(**data, tenant_id=scope.tenant_id, owner_id=owner_id)
    db.add(db_vehicle)
    try:
        await db.commit()
        await db.refresh(db_vehicle)
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            title="Vehicle Already Exists",
            message="A vehicle with these details already exists. Check the fleet list before adding another.",
        )
    
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
    is_investor = current_user.role == UserRole.investor

    # Investor vehicle results are private to the owner, so skip tenant-shared cache entries.
    cached = None if is_investor else await get_cached_vehicle_list(scope.tenant_id, archived=False, status_filter=status_filter)
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)
    
    # Cache miss: fetch from DB
    stmt = select(Vehicle).where(Vehicle.is_archived == False)
    if scope.tenant_id is not None:
        stmt = stmt.where(Vehicle.tenant_id == scope.tenant_id)
    if is_investor:
        stmt = stmt.where(Vehicle.owner_id == current_user.id)
    if status_filter:
        stmt = stmt.where(Vehicle.status == status_filter)
        
    result = await db.execute(stmt)
    vehicles = result.scalars().all()
    
    # Write to cache (5-minute TTL)
    if not is_investor:
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
    is_investor = current_user.role == UserRole.investor

    # Investor vehicle results are private to the owner, so skip tenant-shared cache entries.
    cached = None if is_investor else await get_cached_vehicle_list(scope.tenant_id, archived=True, status_filter=status_filter)
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)
    
    # Cache miss: fetch from DB
    stmt = select(Vehicle).where(Vehicle.is_archived == True)
    if scope.tenant_id is not None:
        stmt = stmt.where(Vehicle.tenant_id == scope.tenant_id)
    if is_investor:
        stmt = stmt.where(Vehicle.owner_id == current_user.id)
    if status_filter:
        stmt = stmt.where(Vehicle.status == status_filter)
        
    result = await db.execute(stmt)
    vehicles = result.scalars().all()
    
    # Write to cache
    if not is_investor:
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
        _assert_future_insurance(update_data["insurance_expiry"])
            
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
        raise BadRequestError(
            title="Vehicle Currently Rented",
            message="This vehicle is currently rented. Complete or cancel its booking before archiving it.",
        )
    if vehicle.is_archived:
        raise BadRequestError(
            title="Already Archived",
            message="This vehicle is already archived.",
        )
    
    # ✅ Check for live bookings (FIXED: was BookingStatus.ongoing → AttributeError)
    await _assert_no_live_bookings(db, vehicle.id, "archiving")
        
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
        raise BadRequestError(
            title="Nothing to Restore",
            message="This vehicle is not archived, so there is nothing to restore.",
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
        raise BadRequestError(
            title="Vehicle Currently Rented",
            message="This vehicle is currently rented. Complete or cancel its booking before deleting it.",
        )
    
    # ✅ Check for live bookings (FIXED: was BookingStatus.ongoing → AttributeError)
    await _assert_no_live_bookings(db, vehicle.id, "deleting")
        
    try:
        await db.delete(vehicle)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise BadRequestError(
            title="Vehicle Has History",
            message="This vehicle has past bookings and cannot be deleted. Archive it instead.",
        )
    
    # ✅ Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
