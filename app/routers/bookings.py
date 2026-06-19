from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingCreate, BookingOut, BookingUpdate
from app.services.contracts import create_contract_for_booking
from app.services.email import (
    send_booking_activated,
    send_booking_cancelled,
    send_booking_completed,
    send_booking_confirmation,
    send_booking_confirmed,
)


router = APIRouter(prefix="/bookings", tags=["bookings"])


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_booking_or_404(booking_id: int, tenant_id: int, db: Session) -> Booking:
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == tenant_id,
    ).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Booking not found"
        )
    return booking


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    booking: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = db.query(Client).filter(
        Client.id == booking.client_id,
        Client.tenant_id == current_user.tenant_id,
    ).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Client not found. Add client first."
        )
    if client.status == ClientStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Suspended clients cannot make new bookings."
        )
    if client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Archived clients cannot make new bookings."
        )

    vehicle = db.query(Vehicle).filter(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id,
    ).first()
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Vehicle not found."
        )
    if vehicle.status != VehicleStatus.available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vehicle is '{vehicle.status.value}'. Only available vehicles can be booked.",
        )
    if vehicle.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Archived vehicles cannot be booked."
        )

    db_booking = Booking(
        **booking.model_dump(),
        tenant_id=current_user.tenant_id,
    )
    db.add(db_booking)
    db.commit()
    create_contract_for_booking(db_booking, db)
    
    if client.email:
        send_booking_confirmation(
            to=client.email,
            client_name=client.full_name,
            booking_id=db_booking.id,
            vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.year})",
            start_date=str(db_booking.start_date),
            end_date=str(db_booking.end_date),
            total_amount=str(db_booking.total_amount),
            currency=db_booking.currency_code,
            contract_number=db_booking.contract.contract_number if db_booking.contract else "—",
        )
    db.refresh(db_booking)
    return db_booking


@router.get("/", response_model=list[BookingOut])
def list_bookings(
    status: BookingStatus | None = None,
    client_id: int | None = None,
    vehicle_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Booking).filter(Booking.tenant_id == current_user.tenant_id)

    # date range searches always include archived bookings
    if start_date or end_date or include_archived:
        pass
    else:
        query = query.filter(Booking.is_archived == False)

    if start_date and end_date:
        query = query.filter(
            Booking.start_date <= end_date,
            Booking.end_date >= start_date,
        )
    elif start_date:
        query = query.filter(Booking.end_date >= start_date)
    elif end_date:
        query = query.filter(Booking.start_date <= end_date)

    if status is not None:
        query = query.filter(Booking.status == status)
    if client_id is not None:
        query = query.filter(Booking.client_id == client_id)
    if vehicle_id is not None:
        query = query.filter(Booking.vehicle_id == vehicle_id)

    return query.order_by(Booking.created_at.desc()).all()


@router.get("/archived", response_model=list[BookingOut])
def list_archived_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Booking).filter(
        Booking.tenant_id == current_user.tenant_id,
        Booking.is_archived == True,
    ).order_by(Booking.archived_at.desc()).all()


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_booking_or_404(booking_id, current_user.tenant_id, db)


@router.patch("/{booking_id}", response_model=BookingOut)
def update_booking(
    booking_id: int,
    updates: BookingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Archived bookings cannot be edited"
        )
    if booking.status in (BookingStatus.completed, BookingStatus.cancelled):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Completed or cancelled bookings cannot be edited"
        )
        
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(booking, field, value)
    db.commit()
    db.refresh(booking)
    return booking


@router.post("/{booking_id}/confirm", response_model=BookingOut)
def confirm_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.status != BookingStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Only pending bookings can be confirmed. Current status: '{booking.status.value}'"
        )
        
    booking.status = BookingStatus.confirmed
    db.commit()
    db.refresh(booking)
    
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    if client and client.email:
        send_booking_confirmed(
            to=client.email,
            client_name=client.full_name,
            booking_id=booking.id,
            vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.year})",
            start_date=str(booking.start_date),
        )
    return booking


@router.post("/{booking_id}/activate", response_model=BookingOut)
def activate_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Only confirmed bookings can be activated. Current status: '{booking.status.value}'"
        )

    client = db.query(Client).filter(Client.id == booking.client_id).first()
    if client.status != ClientStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client must be active to start a trip. Current client status: '{client.status.value}'",
        )

    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    if vehicle.status != VehicleStatus.available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vehicle is not available. Current status: '{vehicle.status.value}'",
        )

    booking.status = BookingStatus.active
    vehicle.status = VehicleStatus.rented
    db.commit()
    db.refresh(booking)
    
    if client.email:
        send_booking_activated(
            to=client.email,
            client_name=client.full_name,
            booking_id=booking.id,
            vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.year})",
            end_date=str(booking.end_date),
        )
    return booking


@router.post("/{booking_id}/complete", response_model=BookingOut)
def complete_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.status != BookingStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Only active bookings can be completed. Current status: '{booking.status.value}'"
        )

    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    booking.status = BookingStatus.completed
    vehicle.status = VehicleStatus.available
    db.commit()
    db.refresh(booking)
    
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    if client and client.email:
        send_booking_completed(
            to=client.email,
            client_name=client.full_name,
            booking_id=booking.id,
            vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.year})",
        )
    return booking


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.status in (BookingStatus.completed, BookingStatus.cancelled):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Cannot cancel a {booking.status.value} booking"
        )

    if booking.status == BookingStatus.active:
        vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
        if vehicle:
            vehicle.status = VehicleStatus.available

    booking.status = BookingStatus.cancelled
    db.commit()
    db.refresh(booking)
    
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    if client and client.email:
        send_booking_cancelled(
            to=client.email,
            client_name=client.full_name,
            booking_id=booking.id,
            vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.year})",
        )
    return booking


@router.post("/{booking_id}/no-show", response_model=BookingOut)
def no_show_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Only confirmed bookings can be marked as no-show. Current status: '{booking.status.value}'"
        )
    booking.status = BookingStatus.no_show
    db.commit()
    db.refresh(booking)
    return booking


@router.post("/{booking_id}/archive", response_model=BookingOut)
def archive_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
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
    db.commit()
    db.refresh(booking)
    return booking


@router.post("/{booking_id}/restore", response_model=BookingOut)
def restore_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if not booking.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Booking is not archived"
        )
    booking.is_archived = False
    booking.archived_at = None
    db.commit()
    db.refresh(booking)
    return booking


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    
    if booking.status == BookingStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Active bookings cannot be deleted. Complete or cancel first."
        )
    db.delete(booking)
    db.commit()