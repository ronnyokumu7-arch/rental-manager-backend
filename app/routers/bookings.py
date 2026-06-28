import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.tenants import Tenant
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingCreate, BookingOut, BookingUpdate
from app.services.contracts import create_contract_for_booking
from app.services.invoices import create_invoice_for_booking # Ensure this service is built
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

# 1. CREATE BOOKING (Now creates a Pending "Quotation")
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
        raise HTTPException(status_code=404, detail="Client not found.")
    if client.status == ClientStatus.suspended or client.is_archived:
        raise HTTPException(status_code=400, detail="Client cannot make bookings.")

    vehicle = db.query(Vehicle).filter(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id,
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if vehicle.status != VehicleStatus.available or vehicle.is_archived:
        raise HTTPException(status_code=409, detail="Vehicle is not available.")

    # Create as PENDING (Quotation stage) - No contract/invoice generated yet
    db_booking = Booking(
        **booking.model_dump(),
        tenant_id=current_user.tenant_id,
        status=BookingStatus.pending,
    )
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
    return db_booking

# 2. CONFIRM BOOKING (Triggers Contract & Invoice Generation)
@router.post("/{booking_id}/confirm", response_model=BookingOut)
def confirm_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status != BookingStatus.pending:
        raise HTTPException(400, "Only pending bookings can be confirmed.")

    booking.status = BookingStatus.confirmed
    
    # Auto-generate documents upon confirmation
    create_contract_for_booking(booking, db)
    create_invoice_for_booking(booking, db)
    
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

# 3. GENERATE QUOTATION LINK
@router.post("/{booking_id}/quote-link", response_model=dict)
def generate_quote_link(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status != BookingStatus.pending:
        raise HTTPException(400, "Can only generate quotes for pending bookings")

    if not booking.share_token:
        booking.share_token = str(uuid.uuid4())
        db.commit()

    base_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return {"share_url": f"{base_url}/quote/{booking.share_token}"}

# 4. PUBLIC: VIEW QUOTATION
@router.get("/public/{token}")
def view_public_quote(token: str, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.share_token == token).first()
    if not booking:
        raise HTTPException(404, "Quotation not found")

    # Expiry: End of the booking's start date
    expiry_limit = booking.start_date.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expiry_limit:
        raise HTTPException(status_code=410, detail="This quotation has expired.")
    if booking.status != BookingStatus.pending:
        raise HTTPException(status_code=410, detail="This quotation is no longer valid.")

    client = db.query(Client).filter(Client.id == booking.client_id).first()
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()

    return {
        "tenant_name": tenant.name if tenant else "Unknown Agency",
        "client_name": client.full_name if client else "Valued Client",
        "vehicle_details": f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})" if vehicle else "Unknown Vehicle",
        "start_date": str(booking.start_date),
        "end_date": str(booking.end_date),
        "pickup_location": booking.pickup_location,
        "return_location": booking.return_location,
        "total_amount": str(booking.total_amount),
        "currency_code": booking.currency_code,
        "expires_at": str(expiry_limit),
    }

# 5. PUBLIC: ACCEPT QUOTATION
@router.post("/public/{token}/accept")
def accept_public_quote(token: str, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.share_token == token).first()
    if not booking:
        raise HTTPException(404, "Quotation not found")

    # Re-verify expiry and status
    expiry_limit = booking.start_date.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expiry_limit:
        raise HTTPException(410, "This quotation has expired.")
    if booking.status != BookingStatus.pending:
        raise HTTPException(400, "This quotation has already been processed.")

    # Accept: Change status and auto-generate Contract + Invoice
    booking.status = BookingStatus.confirmed
    create_contract_for_booking(booking, db)
    create_invoice_for_booking(booking, db)
    
    db.commit()
    return {"message": "Quotation accepted successfully. Booking confirmed."}

# 6. ACTIVATE BOOKING
@router.post("/{booking_id}/activate", response_model=BookingOut)
def activate_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(400, f"Only confirmed bookings can be activated. Current status: '{booking.status.value}'")

    client = db.query(Client).filter(Client.id == booking.client_id).first()
    if client.status != ClientStatus.active:
        raise HTTPException(400, f"Client must be active to start a trip. Current status: '{client.status.value}'")

    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    if vehicle.status != VehicleStatus.available:
        raise HTTPException(400, f"Vehicle is not available. Current status: '{vehicle.status.value}'")

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

# 7. COMPLETE BOOKING
@router.post("/{booking_id}/complete", response_model=BookingOut)
def complete_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status != BookingStatus.active:
        raise HTTPException(400, f"Only active bookings can be completed. Current status: '{booking.status.value}'")

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

# 8. CANCEL BOOKING
@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status in (BookingStatus.completed, BookingStatus.cancelled):
        raise HTTPException(400, f"Cannot cancel a {booking.status.value} booking")

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

# 9. NO-SHOW BOOKING
@router.post("/{booking_id}/no-show", response_model=BookingOut)
def no_show_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(400, f"Only confirmed bookings can be marked as no-show. Current status: '{booking.status.value}'")
    booking.status = BookingStatus.no_show
    db.commit()
    db.refresh(booking)
    return booking

# 10. ARCHIVE / RESTORE / DELETE (Standard maintenance routes)
@router.post("/{booking_id}/archive", response_model=BookingOut)
def archive_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = _get_booking_or_404(booking_id, current_user.tenant_id, db)
    if booking.status == BookingStatus.active:
        raise HTTPException(400, "Active bookings cannot be archived")
    if booking.is_archived:
        raise HTTPException(400, "Booking is already archived")
        
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
        raise HTTPException(400, "Booking is not archived")
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
        raise HTTPException(400, "Active bookings cannot be deleted. Complete or cancel first.")
    db.delete(booking)
    db.commit()
