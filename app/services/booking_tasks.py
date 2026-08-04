# app/services/booking_task_service.py

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.task import TaskPriority
from app.services.task_core import TaskCoreService


class BookingTaskService:
    """Handles all task generation logic specific to the Booking lifecycle."""

    @staticmethod
    async def on_booking_created(db: AsyncSession, booking: Booking, client_name: str, vehicle_plate: str):
        """Triggered when a new booking is created. Creates a single consolidated task for the admin."""
        tenant_id = booking.tenant_id
        booking_id = booking.id
        booking_ref = booking.booking_number or f"#{booking.id}"
        now = datetime.now()

        # 1 Consolidated Task: Admin/Manager to process the new booking
        await TaskCoreService.smart_create_task(
            db=db, 
            tenant_id=tenant_id, 
            target_role="Admin",
            title=f"Process Booking {booking_ref}: Generate Invoice & Contract",
            description=(
                f"New booking created for {client_name} using {vehicle_plate}.\n\n"
                f"Next Steps:\n"
                f"1. Go to the Financials section and generate the Invoice.\n"
                f"2. Generate and send the Contract to the client.\n"
                f"3. Ensure the vehicle is prepared and ready for dispatch on {booking.start_date.strftime('%Y-%m-%d')}."
            ),
            category="operations", 
            priority=TaskPriority.high,
            due_date=now + timedelta(hours=24),
            target_type="booking", 
            target_id=booking_id
        )
