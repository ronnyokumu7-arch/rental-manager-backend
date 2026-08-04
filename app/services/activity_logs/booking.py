from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class BookingActivityLogger:
    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: int, booking, client_name: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="create_booking", target_type="booking", target_id=booking.id, details={"booking_number": booking.booking_number, "client_name": client_name, "total_amount": str(booking.total_amount), "start_date": booking.start_date.isoformat() if booking.start_date else None, "end_date": booking.end_date.isoformat() if booking.end_date else None})

    @staticmethod
    async def on_status_changed(db: AsyncSession, tenant_id: int, user_id: int, booking, old_status: str, new_status: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="update_booking_status", target_type="booking", target_id=booking.id, details={"booking_number": booking.booking_number, "old_status": old_status, "new_status": new_status})

    @staticmethod
    async def on_extended(db: AsyncSession, tenant_id: int, user_id: int, booking, extra_days: int, additional_cost) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="extend_booking", target_type="booking", target_id=booking.id, details={"booking_number": booking.booking_number, "extra_days": extra_days, "additional_cost": str(additional_cost), "new_end_date": booking.end_date.isoformat() if booking.end_date else None})

    @staticmethod
    async def on_archived(db: AsyncSession, tenant_id: int, user_id: int, booking) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="archive_booking", target_type="booking", target_id=booking.id, details={"booking_number": booking.booking_number})
