from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking, BookingStatus
from app.models.users import User
from app.schemas.booking import BookingOut
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.services.cache import invalidate_booking_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/bookings", tags=["vault-bookings"])

@router.get("/", response_model=PaginatedResponse[BookingOut])
@limiter.limit("60/minute")
async def list_vault_bookings(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch bookings that are either archived OR in a terminal state (cancelled/no_show)
    stmt = select(Booking).options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle)
    ).where(
        Booking.tenant_id == current_user.tenant_id,
        or_(
            Booking.is_archived == True,
            Booking.status.in_([BookingStatus.cancelled, BookingStatus.no_show])
        )
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            Booking.booking_number.ilike(search_lower) |
            Booking.destination.ilike(search_lower)
        )
        
    stmt = stmt.order_by(Booking.archived_at.desc().nullslast(), Booking.created_at.desc())
    
    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()
    return paginate_items(bookings, total=len(bookings), page=page, page_size=page_size)

@router.post("/{booking_id}/restore", response_model=BookingOut)
@limiter.limit("10/minute")
async def restore_vault_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Booking).where(
        Booking.id == booking_id,
        Booking.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    booking = result.scalars().first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found in vault")
        
    # Restore logic: Flip the archive flag
    booking.is_archived = False
    booking.archived_at = None
    
    # Note: We leave the status (e.g., 'cancelled') as is. 
    # If you want to force it back to 'pending' upon restore, uncomment below:
    # if booking.status in [BookingStatus.cancelled, BookingStatus.no_show]:
    #     booking.status = BookingStatus.pending
        
    await db.commit()
    await db.refresh(booking)

    # ✅ Invalidate booking cache
    await invalidate_booking_cache(current_user.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_booking", target_type="booking", target_id=booking.id,
        details={"booking_number": booking.booking_number}
    )
    await db.commit()  # Commit the activity log flush

    return booking

@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Booking).where(
        Booking.id == booking_id,
        Booking.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    booking = result.scalars().first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found in vault")
        
    # Capture details before deletion
    booking_number = booking.booking_number
    
    # Hard delete: Permanent destruction from the database
    await db.delete(booking)
    await db.commit()

    # ✅ Invalidate booking cache
    await invalidate_booking_cache(current_user.tenant_id)
    
    # ✅ Log the hard delete action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_booking", target_type="booking", target_id=booking_id,
        details={"booking_number": booking_number}
    )
    await db.commit()  # Commit the activity log flush
