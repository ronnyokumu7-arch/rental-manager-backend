from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.users import User, UserRole
from app.models.vehicles import Vehicle


# ---------------------------------------------------------------------------
# Synchronous Helper (Keep for legacy code, background tasks, or scheduler)
# ---------------------------------------------------------------------------
def get_authorized_vehicle(vehicle_id: int, user: User, db: Session) -> Vehicle:
    """
    Synchronous version for non-async contexts.
    Enforces tenant isolation: tenant users can only access their own vehicles.
    Super admins can access any vehicle.
    """
    # Build query with tenant isolation
    if user.role == UserRole.super_admin:
        # Super admins can access any vehicle
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    else:
        # Tenant users can only access their own tenant's vehicles
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found or access denied"
        )
    return vehicle


# ---------------------------------------------------------------------------
# Asynchronous Helper (Use for all high-traffic API endpoints)
# ---------------------------------------------------------------------------
async def get_authorized_vehicle_async(vehicle_id: int, user: User, db: AsyncSession) -> Vehicle:
    """
    Async version for high-traffic endpoints.
    Enforces tenant isolation: tenant users can only access their own vehicles.
    Super admins can access any vehicle.
    """
    # Build query with tenant isolation
    if user.role == UserRole.super_admin:
        # Super admins can access any vehicle
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    else:
        # Tenant users can only access their own tenant's vehicles
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found or access denied"
        )
    return vehicle
