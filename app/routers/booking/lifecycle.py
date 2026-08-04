from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingOut
from app.services.cache import invalidate_booking_cache, invalidate_vehicle_cache
from ._helpers import get_authorized_booking_async

router = APIRouter()


@router.post("/{booking_id}/confirm", response_model=BookingOut)
@limiter.limit("20/minute")
async def confirm_booking(
    request: Request,
    booking_id: int, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_active_subscription)
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    if booking.status != BookingStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending bookings can be confirmed."
        )
        
    booking.status = BookingStatus.confirmed
    
    await db.commit()
    await db.refresh(booking)
    
    # ✅ Invalidate cache
    await invalidate_booking_cache(current_user.tenant_id)
    
    return booking


@router.post("/{booking_id}/activate", response_model=BookingOut)
@limiter.limit("20/minute")
async def activate_booking(
    request: Request,
    booking_id: int, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_active_subscription)
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only confirmed bookings can be activated."
        )
        
    # ✅ Validate client belongs to tenant and is active
    client_stmt = select(Client).where(
        Client.id == booking.client_id,
        Client.tenant_id == current_user.tenant_id
    )
    client_result = await db.execute(client_stmt)
    client = client_result.scalars().first()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found."
        )
    
    if client.status != ClientStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client must be active to activate a booking."
        )
        
    # ✅ Validate vehicle belongs to tenant and is available
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id
    )
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found."
        )
    
    if vehicle.status != VehicleStatus.available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle is not available."
        )

    booking.status = BookingStatus.active
    vehicle.status = VehicleStatus.rented
    
    await db.commit()
    await db.refresh(booking)
    
    # ✅ Invalidate both booking and vehicle caches
    await invalidate_booking_cache(current_user.tenant_id)
    await invalidate_vehicle_cache(current_user.tenant_id)
    
    return booking


@router.post("/{booking_id}/complete", response_model=BookingOut)
@limiter.limit("20/minute")
async def complete_booking(
    request: Request,
    booking_id: int, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_active_subscription)
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    if booking.status != BookingStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active bookings can be completed."
        )
        
    # ✅ Validate vehicle belongs to tenant
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id
    )
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found."
        )
    
    booking.status = BookingStatus.completed
    vehicle.status = VehicleStatus.awaiting_mileage
    
    await db.commit()
    await db.refresh(booking)
    
    # ✅ Invalidate both booking and vehicle caches
    await invalidate_booking_cache(current_user.tenant_id)
    await invalidate_vehicle_cache(current_user.tenant_id)
    
    return booking


@router.post("/{booking_id}/cancel", response_model=BookingOut)
@limiter.limit("20/minute")
async def cancel_booking(
    request: Request,
    booking_id: int, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_active_subscription)
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    if booking.status in (BookingStatus.completed, BookingStatus.cancelled):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a {booking.status.value} booking."
        )
        
    # ✅ Validate vehicle belongs to tenant
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == booking.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id
    )
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found."
        )
    
    # If booking was active, free up the vehicle
    if booking.status == BookingStatus.active:
        vehicle.status = VehicleStatus.available 
        
    booking.status = BookingStatus.cancelled
    
    await db.commit()
    await db.refresh(booking)
    
    # ✅ Invalidate both booking and vehicle caches
    await invalidate_booking_cache(current_user.tenant_id)
    await invalidate_vehicle_cache(current_user.tenant_id)
    
    return booking


@router.post("/{booking_id}/no-show", response_model=BookingOut)
@limiter.limit("20/minute")
async def no_show_booking(
    request: Request,
    booking_id: int, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_active_subscription)
):
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only confirmed bookings can be marked as no-show."
        )
    
    booking.status = BookingStatus.no_show
    
    await db.commit()
    await db.refresh(booking)
    
    # ✅ Invalidate cache
    await invalidate_booking_cache(current_user.tenant_id)
    
    return booking
