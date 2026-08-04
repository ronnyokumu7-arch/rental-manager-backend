# app/routers/vault/vehicles.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.vehicles import Vehicle, VehicleStatus
from app.models.users import User
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.vehicle import VehicleOut
from app.services.cache import invalidate_vehicle_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/vehicles", tags=["vault-vehicles"])

@router.get("/", response_model=PaginatedResponse[VehicleOut])
@limiter.limit("60/minute")
async def list_vault_vehicles(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch vehicles that are either explicitly archived OR in a 'retired' state
    stmt = select(Vehicle).where(
        Vehicle.tenant_id == current_user.tenant_id,
        or_(
            Vehicle.is_archived == True,
            Vehicle.status == VehicleStatus.retired
        )
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            Vehicle.plate_number.ilike(search_lower) |
            Vehicle.make.ilike(search_lower) |
            Vehicle.model.ilike(search_lower) |
            Vehicle.vin.ilike(search_lower)
        )
        
    stmt = stmt.order_by(Vehicle.archived_at.desc().nullslast(), Vehicle.created_at.desc())
    
    result = await db.execute(stmt)
    vehicles = result.scalars().all()
    return paginate_items(vehicles, total=len(vehicles), page=page, page_size=page_size)

@router.post("/{vehicle_id}/restore", response_model=VehicleOut)
@limiter.limit("10/minute")
async def restore_vault_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Vehicle).where(
        Vehicle.id == vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found in vault")
        
    # Restore logic: Flip the archive flag
    vehicle.is_archived = False
    vehicle.archived_at = None
    
    # If the vehicle was retired, make it available again so it shows up in the active fleet
    if vehicle.status == VehicleStatus.retired:
        vehicle.status = VehicleStatus.available
        
    await db.commit()
    await db.refresh(vehicle)

    # ✅ Invalidate vehicle cache so it appears in active fleet lists
    await invalidate_vehicle_cache(current_user.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_vehicle", target_type="vehicle", target_id=vehicle.id,
        details={"plate_number": vehicle.plate_number}
    )
    await db.commit()  # Commit the activity log flush

    return vehicle

@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Vehicle).where(
        Vehicle.id == vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found in vault")
        
    # Capture details before permanent deletion (object becomes detached after delete)
    vehicle_plate = vehicle.plate_number
        
    # Hard delete: Permanent destruction from the database
    await db.delete(vehicle)
    await db.commit()

    # ✅ Invalidate vehicle cache
    await invalidate_vehicle_cache(current_user.tenant_id)
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_vehicle", target_type="vehicle", target_id=vehicle_id,
        details={"plate_number": vehicle_plate}
    )
    await db.commit()  # Commit the activity log flush
