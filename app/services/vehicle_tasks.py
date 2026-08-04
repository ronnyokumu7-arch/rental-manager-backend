# app/services/vehicle_task_service.py

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicles import Vehicle
from app.models.task import TaskPriority
from app.services.task_core import TaskCoreService


class VehicleTaskService:
    """Handles all task generation logic specific to the Vehicle lifecycle."""

    @staticmethod
    async def on_vehicle_created(db: AsyncSession, vehicle: Vehicle, tenant_id: int):
        """Triggered when a vehicle is created. Checks for missing critical data."""
        missing_fields = []
        if not vehicle.insurance_number: missing_fields.append("Insurance Policy Number")
        if not vehicle.insurance_expiry: missing_fields.append("Insurance Expiry Date")
        if not vehicle.registration_doc: missing_fields.append("Registration Document")
        
        if missing_fields:
            missing_list = ", ".join(missing_fields)
            await TaskCoreService.smart_create_task(
                db=db, tenant_id=tenant_id, target_role="Fleet Manager",
                title=f"Complete Profile for {vehicle.plate_number}",
                description=f"Vehicle is missing critical compliance data: {missing_list}. Please update the vehicle profile to enable activation.",
                category="compliance", priority=TaskPriority.high,
                due_date=datetime.now() + timedelta(hours=24),
                target_type="vehicle", target_id=vehicle.id
            )

    @staticmethod
    async def dispatch_lifecycle_tasks(db: AsyncSession, vehicle: Vehicle, action: str):
        """
        Generates standard tasks based on vehicle status changes.
        Simplified for v1: Only triggers on creation.
        """
        tenant_id = vehicle.tenant_id
        plate = vehicle.plate_number
        now = datetime.now()
        
        if action == "created":
            await TaskCoreService.smart_create_task(
                db=db, tenant_id=tenant_id, target_role="Fleet Manager",
                title=f"Verify Documents & Inspect {plate}",
                description=f"New vehicle added. Verify VIN, upload registration/insurance, and conduct physical inspection.",
                category="fleet", priority=TaskPriority.high,
                due_date=now + timedelta(hours=24),
                target_type="vehicle", target_id=vehicle.id
            )
