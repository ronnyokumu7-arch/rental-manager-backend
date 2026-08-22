from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.models.bookings import Booking
from app.models.users import User, UserRole


# ---------------------------------------------------------------------------
# Synchronous Helper (Keep for legacy code, background tasks, or scheduler)
# ---------------------------------------------------------------------------
def get_authorized_booking(booking_id: int, user: User, db: Session) -> Booking:
    """
    Synchronous version for non-async contexts.
    Enforces tenant isolation: tenant users can only access their own bookings.
    Super admins can access any booking.

    ✅ MILESTONE 2: Eager-loads client/vehicle/driver so the returned entity
    serializes safely through BookingOut (no lazy-load in async contexts).
    """
    if user.role == UserRole.super_admin:
        stmt = select(Booking).where(Booking.id == booking_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Booking).where(
            Booking.id == booking_id,
            Booking.tenant_id == user.tenant_id
        )

    stmt = stmt.options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver),  # ✅ MILESTONE 2
    )

    result = db.execute(stmt)
    booking = result.scalars().first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found or access denied"
        )
    return booking


# ---------------------------------------------------------------------------
# Asynchronous Helper (Use for all high-traffic API endpoints)
# ---------------------------------------------------------------------------
async def get_authorized_booking_async(booking_id: int, user: User, db: AsyncSession) -> Booking:
    """
    Async version for high-traffic endpoints.
    Enforces tenant isolation: tenant users can only access their own bookings.
    Super admins can access any booking.

    ✅ MILESTONE 2: Eager-loads client/vehicle/driver so the returned entity
    serializes safely through BookingOut (prevents MissingGreenlet).
    """
    if user.role == UserRole.super_admin:
        stmt = select(Booking).where(Booking.id == booking_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Booking).where(
            Booking.id == booking_id,
            Booking.tenant_id == user.tenant_id
        )

    stmt = stmt.options(
        selectinload(Booking.client),
        selectinload(Booking.vehicle),
        selectinload(Booking.driver),  # ✅ MILESTONE 2
    )

    result = await db.execute(stmt)
    booking = result.scalars().first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found or access denied"
        )
    return booking
