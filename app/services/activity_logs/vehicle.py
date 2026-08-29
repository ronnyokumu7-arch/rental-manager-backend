# app/services/activity_logs/vehicle.py

from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService


class VehicleActivityLogger:
    """Activity logging helpers for vehicle lifecycle and operational events."""

    @staticmethod
    async def on_rented(db: AsyncSession, tenant_id: int, user_id: int, vehicle, booking_number: str, client_name: str = None) -> None:
        """
        Log a vehicle rental event.

        ✅ CRITICAL: New rentals are High Priority (Revenue).
        """
        summary = {
            "vehicle_name": f"{vehicle.make} {vehicle.model}",
            "plate_number": vehicle.plate_number,
            "booking_number": booking_number,
            "client_name": client_name,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="vehicle_rented",
            label="Vehicle Rented",
            target_type="vehicle",
            target_id=vehicle.id,
            summary=summary,
            details={
                "plate_number": vehicle.plate_number,
                "booking_number": booking_number,
                "client_name": client_name,
            },
            priority=3,  # High (Revenue)
        )

    @staticmethod
    async def on_returned(db: AsyncSession, tenant_id: int, user_id: int, vehicle, booking_number: str, client_name: str = None) -> None:
        """
        Log a vehicle return event.
        """
        summary = {
            "vehicle_name": f"{vehicle.make} {vehicle.model}",
            "plate_number": vehicle.plate_number,
            "booking_number": booking_number,
            "client_name": client_name,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="vehicle_returned",
            label="Vehicle Returned",
            target_type="vehicle",
            target_id=vehicle.id,
            summary=summary,
            details={
                "plate_number": vehicle.plate_number,
                "booking_number": booking_number,
                "client_name": client_name,
            },
            priority=2,  # Normal
        )
