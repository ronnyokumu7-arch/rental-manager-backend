from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.vehicle import VehicleCreate, VehicleOut, VehicleUpdate


router = APIRouter(prefix="/vehicles", tags=["vehicles"])


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_authorized_vehicle(vehicle_id: int, user: User, db: Session) -> Vehicle:
    """Retrieve a vehicle and enforce tenant ownership."""
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.tenant_id == user.tenant_id
    ).first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Vehicle not found"
        )
    return vehicle


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    db_vehicle = Vehicle(**vehicle.model_dump(), tenant_id=current_user.tenant_id)
    db.add(db_vehicle)
    db.commit()
    db.refresh(db_vehicle)
    return db_vehicle


@router.get("/", response_model=list[VehicleOut])
def read_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Vehicle).filter(
        Vehicle.tenant_id == current_user.tenant_id,
        Vehicle.is_archived == False,
    ).all()


@router.get("/archived", response_model=list[VehicleOut])
def read_archived_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Vehicle).filter(
        Vehicle.tenant_id == current_user.tenant_id,
        Vehicle.is_archived == True,
    ).all()


@router.get("/{vehicle_id}", response_model=VehicleOut)
def read_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_authorized_vehicle(vehicle_id, current_user, db)


@router.patch("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int,
    updates: VehicleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
        
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post("/{vehicle_id}/maintenance", response_model=VehicleOut)
def send_to_maintenance(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.retired:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Retired vehicles cannot be sent to maintenance")
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is currently rented. Complete or cancel the active booking first")
    if vehicle.status == VehicleStatus.maintenance:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is already in maintenance")
    
    vehicle.status = VehicleStatus.maintenance
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post("/{vehicle_id}/reactivate", response_model=VehicleOut)
def reactivate_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.retired:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Retired vehicles cannot be reactivated")
    if vehicle.status == VehicleStatus.available:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is already available")
    
    vehicle.status = VehicleStatus.available
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post("/{vehicle_id}/retire", response_model=VehicleOut)
def retire_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is currently rented. Complete or cancel the active booking first")
    if vehicle.status == VehicleStatus.retired:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is already retired")
    
    vehicle.status = VehicleStatus.retired
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post("/{vehicle_id}/archive", response_model=VehicleOut)
def archive_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is currently rented and cannot be archived")
    if vehicle.is_archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is already archived")
    
    vehicle.is_archived = True
    vehicle.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post("/{vehicle_id}/restore", response_model=VehicleOut)
def restore_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    if not vehicle.is_archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is not archived")
    
    vehicle.is_archived = False
    vehicle.archived_at = None
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    vehicle = _get_authorized_vehicle(vehicle_id, current_user, db)
    
    if vehicle.status == VehicleStatus.rented:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is currently rented and cannot be deleted")
        
    db.delete(vehicle)
    db.commit()