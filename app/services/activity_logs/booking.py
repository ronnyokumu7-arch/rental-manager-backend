from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService


class BookingActivityLogger:
    """Logger for Booking lifecycle events."""
    
    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: int, booking, client_name: str) -> None:
        """
        Log a booking creation event.
        
        ✅ SNAPSHOT PATTERN: Builds a human-readable summary with 
        client and vehicle details to prevent MissingGreenlet errors.
        """
        summary = {
            "client_name": client_name,
            "client_phone": getattr(booking.client, "phone", None) if booking.client else None,
            "booking_number": booking.booking_number,
            "amount": f"KES {booking.total_amount:,.2f}" if booking.total_amount else None,
            "start_date": booking.start_date.isoformat() if booking.start_date else None,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
            "vehicle": f"{booking.vehicle.make} {booking.vehicle.model}" if booking.vehicle else None,
            "plate_number": booking.vehicle.plate_number if booking.vehicle else None,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="create_booking",
            label="Booking Created",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
                "client_name": client_name,
                "total_amount": str(booking.total_amount),
                "start_date": booking.start_date.isoformat() if booking.start_date else None,
                "end_date": booking.end_date.isoformat() if booking.end_date else None,
            },
            priority=2,
        )

    @staticmethod
    async def on_status_changed(db: AsyncSession, tenant_id: int, user_id: int, booking, old_status: str, new_status: str) -> None:
        """
        Log a booking status change event.
        
        ✅ CRITICAL: Trip Overdue and Trip Ending Today are flagged as High Priority.
        """
        priority = 2
        if new_status == "active":
            priority = 3
        elif new_status == "completed":
            priority = 2
        
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "client_phone": getattr(booking.client, "phone", None) if booking.client else None,
            "booking_number": booking.booking_number,
            "old_status": old_status,
            "new_status": new_status,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="update_booking_status",
            label=f"Booking {new_status.replace('_', ' ').title()}",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
                "old_status": old_status,
                "new_status": new_status,
            },
            priority=priority,
        )

    @staticmethod
    async def on_extended(db: AsyncSession, tenant_id: int, user_id: int, booking, extra_days: int, additional_cost) -> None:
        """
        Log a booking extension event.
        """
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "client_phone": getattr(booking.client, "phone", None) if booking.client else None,
            "booking_number": booking.booking_number,
            "extra_days": extra_days,
            "additional_cost": f"KES {additional_cost:,.2f}" if additional_cost else None,
            "new_end_date": booking.end_date.isoformat() if booking.end_date else None,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="extend_booking",
            label="Booking Extended",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
                "extra_days": extra_days,
                "additional_cost": str(additional_cost),
                "new_end_date": booking.end_date.isoformat() if booking.end_date else None,
            },
            priority=2,
        )

    @staticmethod
    async def on_archived(db: AsyncSession, tenant_id: int, user_id: int, booking) -> None:
        """
        Log a booking archive event.
        """
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "booking_number": booking.booking_number,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="archive_booking",
            label="Booking Archived",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
            },
            priority=2,
        )

    # ✅ NEW: Booking Updated
    @staticmethod
    async def on_updated(db: AsyncSession, tenant_id: int, user_id: int, booking, changed_fields: list[str]) -> None:
        """
        Log a booking update event.
        """
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "booking_number": booking.booking_number,
            "changed_fields": changed_fields,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="update_booking",
            label="Booking Updated",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
                "changed_fields": changed_fields,
            },
            priority=2,
        )

    # ✅ NEW: Booking Restored
    @staticmethod
    async def on_restored(db: AsyncSession, tenant_id: int, user_id: int, booking) -> None:
        """
        Log a booking restore event.
        """
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "booking_number": booking.booking_number,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="restore_booking",
            label="Booking Restored",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
            },
            priority=2,
        )

    # ✅ NEW: Trip Ending Today (Daily Scheduler)
    @staticmethod
    async def on_trip_ending_today(db: AsyncSession, tenant_id: int, user_id: int, booking) -> None:
        """
        Log a critical alert: Trip ending today.
        """
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "client_phone": getattr(booking.client, "phone", None) if booking.client else None,
            "booking_number": booking.booking_number,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
            "vehicle": f"{booking.vehicle.make} {booking.vehicle.model}" if booking.vehicle else None,
            "plate_number": booking.vehicle.plate_number if booking.vehicle else None,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="trip_ending_today",
            label="Trip Ending Today",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
                "end_date": booking.end_date.isoformat() if booking.end_date else None,
            },
            priority=3,  # High
        )

    # ✅ NEW: Trip Overdue (Daily Scheduler)
    @staticmethod
    async def on_trip_overdue(db: AsyncSession, tenant_id: int, user_id: int, booking) -> None:
        """
        Log a critical alert: Trip is overdue.
        """
        summary = {
            "client_name": getattr(booking.client, "full_name", None) if booking.client else None,
            "client_phone": getattr(booking.client, "phone", None) if booking.client else None,
            "booking_number": booking.booking_number,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
            "vehicle": f"{booking.vehicle.make} {booking.vehicle.model}" if booking.vehicle else None,
            "plate_number": booking.vehicle.plate_number if booking.vehicle else None,
        }
        
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="trip_overdue",
            label="Trip Overdue",
            target_type="booking",
            target_id=booking.id,
            summary=summary,
            details={
                "booking_number": booking.booking_number,
                "end_date": booking.end_date.isoformat() if booking.end_date else None,
            },
            priority=4,  # Critical
        )
