from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class VehicleActivityLogger:
    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: int, vehicle) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="create_vehicle", target_type="vehicle", target_id=vehicle.id, details={"make": vehicle.make, "model": vehicle.model, "plate_number": vehicle.plate_number})

    @staticmethod
    async def on_status_changed(db: AsyncSession, tenant_id: int, user_id: int, vehicle, old_status: str, new_status: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="update_vehicle_status", target_type="vehicle", target_id=vehicle.id, details={"plate_number": vehicle.plate_number, "old_status": old_status, "new_status": new_status})

    @staticmethod
    async def on_archived(db: AsyncSession, tenant_id: int, user_id: int, vehicle) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="archive_vehicle", target_type="vehicle", target_id=vehicle.id, details={"plate_number": vehicle.plate_number})
