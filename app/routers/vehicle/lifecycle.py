# app/routers/vehicle/lifecycle.py
"""
✅ VEHICLE LIFECYCLE — activate / maintenance / reactivate / retire / mileage.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B):
  - reactivate no longer accepts rented vehicles (double-rent race).
  - reactivate no longer bypasses the insurance gate (pending_activation).
  - Insurance/mileage guards return field_errors for form highlighting.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError
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
        raise BadRequestError(
            title="Not Awaiting Activation",
            message="Only vehicles awaiting activation can be activated.",
        )

    # ✅ KYC-style gate: field-level errors for the insurance form
    missing_insurance: dict[str, str] = {}
    if not vehicle.insurance_number:
        missing_insurance["insurance_number"] = "Policy number is required"
    if not vehicle.insurance_expiry:
        missing_insurance["insurance_expiry"] = "Expiry date is required"
    if missing_insurance:
        raise BadRequestError(
            title="Insurance Details Missing",
            message="Add the insurance policy number and expiry date before activating this vehicle.",
            field_errors=missing_insurance,
        )
    if vehicle.insurance_expiry <= datetime.now(timezone.utc):
        raise BadRequestError(
            title="Insurance Expired",
            message="This vehicle's insurance has expired. Update the policy details before activation.",
            field_errors={"insurance_expiry": "Policy has expired — update it first"},
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
        raise BadRequestError(
            title="Vehicle Retired",
            message="This vehicle is retired and cannot be sent to maintenance.",
        )
    if vehicle.status == VehicleStatus.rented:
        raise BadRequestError(
            title="Vehicle Currently Rented",
            message="This vehicle is currently rented. Complete or cancel its booking before sending it to maintenance.",
        )
    if vehicle.status == VehicleStatus.maintenance:
        raise BadRequestError(
            title="Already in Maintenance",
            message="This vehicle is already in maintenance.",
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
        raise BadRequestError(
            title="Vehicle Retired",
            message="This vehicle is retired and cannot be reactivated.",
        )
    if vehicle.status == VehicleStatus.available:
        raise BadRequestError(
            title="Already Available",
            message="This vehicle is already available.",
        )
    # ✅ Phase B: rented vehicles can't flip to available mid-trip (double-rent race)
    if vehicle.status == VehicleStatus.rented:
        raise BadRequestError(
            title="Vehicle Currently Rented",
            message="This vehicle is on a trip. Complete or cancel its booking before changing its status.",
        )
    # ✅ Phase B: pending_activation must go through Activate (insurance gate)
    if vehicle.status == VehicleStatus.pending_activation:
        raise BadRequestError(
            title="Not Yet Activated",
            message="This vehicle hasn't completed its first activation. Use Activate after adding insurance details.",
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
    db: AsyncSession = Depends(require_active_subscription),
):
    vehicle = await get_authorized_vehicle_async(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise BadRequestError(
            title="Vehicle Currently Rented",
            message="This vehicle is currently rented. Complete or cancel its booking before retiring it.",
        )
    if vehicle.status == VehicleStatus.retired:
        raise BadRequestError(
            title="Already Retired",
            message="This vehicle is already retired.",
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
        raise BadRequestError(
            title="Mileage Not Due",
            message="Update mileage only when it is due or when the vehicle is available or in maintenance.",
        )
        
    # 2. Validate Logic: Odometer must move forward
    if payload.current_mileage < vehicle.current_mileage:
        raise BadRequestError(
            title="Invalid Mileage",
            message=f"Enter mileage equal to or greater than the current mileage of {vehicle.current_mileage} km.",
            field_errors={"current_mileage": f"Must be ≥ {vehicle.current_mileage} km"},
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
