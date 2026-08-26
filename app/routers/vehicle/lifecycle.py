from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.subscription import require_active_subscription
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.vehicle import VehicleOut, MileageUpdatePayload
from app.services.cache import invalidate_vehicle_cache  # ✅ NEW: Cache invalidation
from ._helpers import get_authorized_vehicle_async

router = APIRouter()


# ---------------------------------------------------------------------------
# LIFECYCLE STATE CHANGES
# ---------------------------------------------------------------------------

@router.post("/{vehicle_id}/activate", response_model=VehicleOut)
@limiter.limit("15/minute")
async def activate_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status != VehicleStatus.pending_activation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only vehicles pending activation can be activated."
        )
    if not vehicle.insurance_number or not vehicle.insurance_expiry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insurance policy number and expiry date are required before activation."
        )
    if vehicle.insurance_expiry <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insurance is already expired. Cannot activate vehicle."
        )
        
    vehicle.status = VehicleStatus.available
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ CRITICAL: Invalidate cache so vehicle status updates immediately
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle


@router.post("/{vehicle_id}/maintenance", response_model=VehicleOut)
@limiter.limit("15/minute")
async def send_to_maintenance(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.retired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retired vehicles cannot be sent to maintenance."
        )
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is currently rented."
        )
    if vehicle.status == VehicleStatus.maintenance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is already in maintenance."
        )
        
    vehicle.status = VehicleStatus.maintenance
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle


@router.post("/{vehicle_id}/reactivate", response_model=VehicleOut)
@limiter.limit("15/minute")
async def reactivate_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.retired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retired vehicles cannot be reactivated."
        )
    if vehicle.status == VehicleStatus.available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is already available."
        )
        
    vehicle.status = VehicleStatus.available
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle


@router.post("/{vehicle_id}/retire", response_model=VehicleOut)
@limiter.limit("15/minute")
async def retire_vehicle(
    request: Request,
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot retire a vehicle that is currently rented."
        )
    if vehicle.status == VehicleStatus.retired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is already retired."
        )
        
    vehicle.status = VehicleStatus.retired
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle


# =============================================================================
# ✅ MILEAGE UPDATE: Uses mileage_due flag (awaiting_mileage removed)
# =============================================================================

@router.patch("/{vehicle_id}/update-mileage", response_model=VehicleOut)
@limiter.limit("20/minute")
async def update_vehicle_mileage(
    request: Request,
    vehicle_id: int,
    payload: MileageUpdatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    # 1. Enforce State: Accept when mileage_due=True (trip return) OR status is operational
    if not vehicle.mileage_due and vehicle.status not in (
        VehicleStatus.available, 
        VehicleStatus.maintenance
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mileage can only be updated for vehicles with pending mileage or in operational status."
        )
        
    # 2. Validate Logic: Odometer must move forward
    if payload.current_mileage < vehicle.current_mileage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New mileage ({payload.current_mileage} km) must be greater than or equal to current mileage ({vehicle.current_mileage} km)."
        )
        
    # 3. Apply Updates
    vehicle.current_mileage = payload.current_mileage
    if payload.next_service_km is not None:
        vehicle.next_service_km = payload.next_service_km
        
    # 4. Clear the mileage_due flag (operator has logged the return)
    vehicle.mileage_due = False
    
    await db.commit()
    await db.refresh(vehicle)
    
    # ✅ CRITICAL: Invalidate cache
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return vehicle
