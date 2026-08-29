from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .service import ActivityLogService


def _rel(obj, name: str):
    """
    ✅ SAFE RELATIONSHIP READ — no lazy-load, no MissingGreenlet.
    Returns the related object ONLY if already loaded in memory
    (eager-loaded or passed in); otherwise None.
    """
    if obj is None:
        return None
    return obj.__dict__.get(name)


class BookingActivityLogger:
    """Logger for Booking lifecycle events."""

    @staticmethod
    async def on_created(
        db: AsyncSession,
        tenant_id: int,
        user_id: Optional[int],
        booking,
        client_name: str,
        client=None,   # ✅ caller passes already-loaded objects when available
        vehicle=None,
    ) -> None:
        client = client or _rel(booking, "client")
        vehicle = vehicle or _rel(booking, "vehicle")

        summary = {
            "client_name": client_name or (client.full_name if client else None),
            "client_phone": client.phone if client else None,
            "booking_number": booking.booking_number,
            "amount": f"KES {booking.total_amount:,.2f}" if booking.total_amount else None,
            "start_date": booking.start_date.isoformat() if booking.start_date else None,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
            "vehicle": f"{vehicle.make} {vehicle.model}" if vehicle else None,
            "plate_number": vehicle.plate_number if vehicle else None,
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
    async def on_status_changed(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking, old_status: str, new_status: str) -> None:
        priority = 2
        if new_status == "active":
            priority = 3

        client = _rel(booking, "client")
        summary = {
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
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
    async def on_extended(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking, extra_days: int, additional_cost) -> None:
        client = _rel(booking, "client")
        summary = {
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
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
    async def on_archived(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking) -> None:
        client = _rel(booking, "client")
        summary = {
            "client_name": client.full_name if client else None,
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
            details={"booking_number": booking.booking_number},
            priority=2,
        )

    @staticmethod
    async def on_updated(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking, changed_fields: list[str]) -> None:
        client = _rel(booking, "client")
        summary = {
            "client_name": client.full_name if client else None,
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

    @staticmethod
    async def on_restored(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking) -> None:
        client = _rel(booking, "client")
        summary = {
            "client_name": client.full_name if client else None,
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
            details={"booking_number": booking.booking_number},
            priority=2,
        )

    @staticmethod
    async def on_trip_ending_today(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking) -> None:
        client = _rel(booking, "client")
        vehicle = _rel(booking, "vehicle")
        summary = {
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "booking_number": booking.booking_number,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
            "vehicle": f"{vehicle.make} {vehicle.model}" if vehicle else None,
            "plate_number": vehicle.plate_number if vehicle else None,
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

    @staticmethod
    async def on_trip_overdue(db: AsyncSession, tenant_id: int, user_id: Optional[int], booking) -> None:
        client = _rel(booking, "client")
        vehicle = _rel(booking, "vehicle")
        summary = {
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "booking_number": booking.booking_number,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
            "vehicle": f"{vehicle.make} {vehicle.model}" if vehicle else None,
            "plate_number": vehicle.plate_number if vehicle else None,
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
