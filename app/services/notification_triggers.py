"""
Notification Triggers — Domain-specific helpers to fire notifications 
from business logic services without bloating them.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification import NotificationService
from app.models.notifications import NotificationType, NotificationPriority


class NotificationTriggers:
    """Static methods to trigger specific business events as notifications."""

    @staticmethod
    async def on_booking_completed(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        booking_number: str,
        client_name: str,
        booking_id: int,
    ) -> None:
        """Triggered when a trip is completed and mileage is due."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.vehicle,
            priority=NotificationPriority.normal,
            title="Trip Completed & Mileage Due",
            message=f"Booking {booking_number} for {client_name} has been completed. Please update the vehicle mileage.",
            action_url=f"/dashboard/bookings/{booking_id}",
            metadata={"booking_id": booking_id, "client_name": client_name},
        )

    @staticmethod
    async def on_payment_received(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        amount: float,
        client_name: str,
        payment_id: int,
    ) -> None:
        """Triggered when a new payment is recorded."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.payment,
            priority=NotificationPriority.high,
            title="Payment Received",
            message=f"A payment of {amount} has been successfully recorded for {client_name}.",
            action_url=f"/dashboard/financials/payments/{payment_id}",
            metadata={"payment_id": payment_id, "amount": amount},
        )

    @staticmethod
    async def on_contract_signed(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        booking_number: str,
        client_name: str,
        booking_id: int,
    ) -> None:
        """Triggered when a client signs a rental contract."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.client,
            priority=NotificationPriority.high,
            title="Contract Signed",
            message=f"{client_name} has signed the rental contract for booking {booking_number}.",
            action_url=f"/dashboard/bookings/{booking_id}",
            metadata={"booking_id": booking_id, "client_name": client_name},
        )

    @staticmethod
    async def on_commission_accrued(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int, # Usually super-admin or finance role
        amount: float,
        booking_number: str,
    ) -> None:
        """Triggered when a PAYG commission event is created."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.system,
            priority=NotificationPriority.low,
            title="Commission Accrued",
            message=f"Commission of {amount} accrued for booking {booking_number}.",
            action_url="/dashboard/financials/commission",
            metadata={"amount": amount, "booking_number": booking_number},
        )

    @staticmethod
    async def on_commission_payment_submitted(
        db: AsyncSession,
        tenant_id: int,
        amount: float,
        reference: str,
        payment_id: int,
    ) -> None:
        """Triggered when a tenant submits a commission payment. Notifies Super Admins."""
        from app.models.users import User, UserRole
        # Find all super admins to notify
        stmt = select(User.id).where(User.role == UserRole.super_admin, User.is_active == True)
        result = await db.execute(stmt)
        super_admin_ids = [row[0] for row in result.fetchall()]

        if super_admin_ids:
            await NotificationService.create(
                db=db,
                tenant_id=tenant_id, # Use the tenant_id for context, even though it's a platform event
                user_ids=super_admin_ids,
                type=NotificationType.payment,
                priority=NotificationPriority.normal,
                title="Commission Payment Submitted",
                message=f"A commission payment of {amount} (Ref: {reference}) is awaiting verification.",
                action_url=f"/super-admin/commission/payments?status=pending",
                metadata={"payment_id": payment_id, "amount": amount, "reference": reference},
            )

    @staticmethod
    async def on_commission_payment_verified(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        amount: float,
        reference: str,
        payment_id: int,
    ) -> None:
        """Triggered when a super admin verifies a commission payment. Notifies the Tenant Owner."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.payment,
            priority=NotificationPriority.high,
            title="Commission Payment Verified",
            message=f"Your commission payment of {amount} (Ref: {reference}) has been verified. Your account is now in good standing.",
            action_url="/dashboard/commission",
            metadata={"payment_id": payment_id, "amount": amount, "reference": reference},
        )

    @staticmethod
    async def on_booking_confirmed(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        booking_number: str,
        client_name: str,
        booking_id: int,
    ) -> None:
        """Triggered when a booking is confirmed."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.booking,
            priority=NotificationPriority.normal,
            title="Booking Confirmed",
            message=f"Booking {booking_number} for {client_name} has been confirmed.",
            action_url=f"/dashboard/bookings/{booking_id}",
            metadata={"booking_id": booking_id, "client_name": client_name},
        )

    @staticmethod
    async def on_trip_started(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        booking_number: str,
        client_name: str,
        booking_id: int,
    ) -> None:
        """Triggered when a trip starts (vehicle handed over)."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.vehicle,
            priority=NotificationPriority.high,
            title="Trip Started",
            message=f"Trip for booking {booking_number} ({client_name}) has started. Vehicle is now rented.",
            action_url=f"/dashboard/bookings/{booking_id}",
            metadata={"booking_id": booking_id, "client_name": client_name},
        )

    @staticmethod
    async def on_booking_cancelled(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        booking_number: str,
        client_name: str,
        booking_id: int,
        reason: str,
    ) -> None:
        """Triggered when a booking is cancelled."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.booking,
            priority=NotificationPriority.high,
            title="Booking Cancelled",
            message=f"Booking {booking_number} for {client_name} has been cancelled. Reason: {reason}.",
            action_url=f"/dashboard/bookings/{booking_id}",
            metadata={"booking_id": booking_id, "client_name": client_name, "reason": reason},
        )
