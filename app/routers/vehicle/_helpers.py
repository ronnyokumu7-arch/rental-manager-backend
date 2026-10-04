# app/routers/vehicle/_helpers.py
"""
✅ Shared tenant/investor-isolation guards for vehicle endpoints.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ SECURITY: the 404 copy intentionally conflates "not found" and "no access"
   to prevent vehicle-ID enumeration — preserved as-is.
✅ SCOPING: investors see ONLY their own vehicles (owner_id); super admins see all.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, NotFoundError
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
    if user.role == UserRole.investor:
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.tenant_id == user.tenant_id,
            Vehicle.owner_id == user.id,
        )
    elif user.role == UserRole.super_admin:
        # Super admins can access any vehicle
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    else:
        # Tenant users can only access their own tenant's vehicles
        if user.tenant_id is None:
            raise AuthorizationError(
                title="No Agency Linked",
                message="Your account isn't linked to an agency. Contact your administrator for access.",
            )
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise NotFoundError(
            title="Vehicle Not Found",
            message="We couldn't find this vehicle, or you may not have access to it.",
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
    if user.role == UserRole.investor:
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.tenant_id == user.tenant_id,
            Vehicle.owner_id == user.id,
        )
    elif user.role == UserRole.super_admin:
        # Super admins can access any vehicle
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    else:
        # Tenant users can only access their own tenant's vehicles
        if user.tenant_id is None:
            raise AuthorizationError(
                title="No Agency Linked",
                message="Your account isn't linked to an agency. Contact your administrator for access.",
            )
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise NotFoundError(
            title="Vehicle Not Found",
            message="We couldn't find this vehicle, or you may not have access to it.",
        )
    return vehicle
