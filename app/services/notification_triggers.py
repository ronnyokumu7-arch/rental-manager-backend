"""
Notification Triggers — Domain-specific helpers to fire notifications 
from business logic services without bloating them.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification import NotificationService
from app.models.notifications import NotificationType, NotificationPriority


def _fmt_recorded_at() -> tuple[str, str]:
    """Returns (date_str, time_str) for 'recorded on {date} at {time}' copy."""
    now = datetime.now(timezone.utc)
    return now.strftime("%d/%m/%y"), now.strftime("%H:%M")


class NotificationTriggers:
    """Static methods to trigger specific business events as notifications."""

    # ─── PAYMENTS — ESTABLISHED PLAN (do not change) ───────────────────────
    @staticmethod
    async def on_payment_received(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        amount: float,
        client_name: str,
        payment_id: int,
        reference: str = None,
        invoice_number: str = None,
        currency_code: str = "KES",
    ) -> None:
        """Triggered when the agency confirms a payment."""
        date_str, time_str = _fmt_recorded_at()
        ref_lead = f"Ref {reference} confirmed." if reference else "Payment confirmed."
        inv_part = f" for {invoice_number}" if invoice_number else ""
        message = (
            f"{ref_lead} {currency_code} {amount:,.2f}{inv_part} "
            f"recorded on {date_str} at {time_str}."
        )
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.payment,
            priority=NotificationPriority.high,
            title="Payment Confirmed",
            message=message,
            action_url=f"/dashboard/financials/payments/{payment_id}",
            payload={
                "payment_id": payment_id,
                "amount": amount,
                "reference": reference,
                "invoice_number": invoice_number,
                "action_label": "View payment",
            },
        )

    @staticmethod
    async def on_payment_submitted(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        amount: float,
        reference: str,
        payment_id: int,
        invoice_number: str = None,
        currency_code: str = "KES",
    ) -> None:
        """Triggered when a client submits a payment proof via public link. Notifies the Agency."""
        date_str, time_str = _fmt_recorded_at()
        inv_part = f" for {invoice_number}" if invoice_number else ""
        message = (
            f"Ref {reference} awaiting confirmation. "
            f"{currency_code} {amount:,.2f}{inv_part} "
            f"recorded on {date_str} at {time_str}."
        )
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.payment,
            priority=NotificationPriority.high,
            title="Incoming Payment",
            message=message,
            action_url="/dashboard/financials?tab=payments",
            payload={
                "payment_id": payment_id,
                "amount": amount,
                "reference": reference,
                "invoice_number": invoice_number,
                "action_label": "Confirm payment received",
            },
        )

    # ─── CONTRACTS ─────────────────────────────────────────────────────────
    @staticmethod
    async def on_contract_signed(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        booking_number: str,
        client_name: str,
        booking_id: int,
        contract_number: str,
    ) -> None:
        """Triggered when a client signs a rental contract."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.contract,
            priority=NotificationPriority.high,
            title="Contract Signed",
            message=f"{client_name} signed contract {contract_number} for booking {booking_number}.",
            action_url=f"/dashboard/financials?tab=contracts&search={contract_number}",
            payload={
                "booking_id": booking_id,
                "client_name": client_name,
                "contract_number": contract_number,
                "action_label": "View contract",
            },
        )

    # ─── BOOKINGS / TRIPS ──────────────────────────────────────────────────
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
            message=f"Booking {booking_number} for {client_name} is confirmed and ready for contract & trip.",
            action_url=f"/dashboard/bookings/{booking_id}",
            payload={
                "booking_id": booking_id,
                "client_name": client_name,
                "action_label": "View booking",
            },
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
            message=f"Trip started for {client_name} on booking {booking_number} — vehicle now marked as rented.",
            action_url=f"/dashboard/bookings/{booking_id}",
            payload={
                "booking_id": booking_id,
                "client_name": client_name,
                "action_label": "View booking",
            },
        )

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
            message=f"Trip for {client_name} on booking {booking_number} completed — mileage update now due.",
            action_url=f"/dashboard/bookings/{booking_id}",
            payload={
                "booking_id": booking_id,
                "client_name": client_name,
                "action_label": "Update mileage",
            },
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
            message=f"Booking {booking_number} for {client_name} was cancelled ({reason}).",
            action_url=f"/dashboard/bookings/{booking_id}",
            payload={
                "booking_id": booking_id,
                "client_name": client_name,
                "reason": reason,
                "action_label": "View booking",
            },
        )

    # ─── CLIENTS / VEHICLES ────────────────────────────────────────────────
    @staticmethod
    async def on_client_created(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        client_name: str,
        client_id: int,
    ) -> None:
        """Triggered when a new client is added to the system."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.client,
            priority=NotificationPriority.low,
            title="New Client Added",
            message=f"New client {client_name} added to your roster.",
            action_url=f"/dashboard/clients/{client_id}",
            payload={
                "client_id": client_id,
                "client_name": client_name,
                "action_label": "View client",
            },
        )

    @staticmethod
    async def on_vehicle_created(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
        vehicle_plate: str,
        vehicle_id: int,
    ) -> None:
        """Triggered when a new vehicle is added to the fleet."""
        await NotificationService.create(
            db=db,
            tenant_id=tenant_id,
            user_ids=target_user_id,
            type=NotificationType.vehicle,
            priority=NotificationPriority.low,
            title="New Vehicle Added",
            message=f"New vehicle {vehicle_plate} added to your fleet.",
            action_url=f"/dashboard/fleet/{vehicle_id}",
            payload={
                "vehicle_id": vehicle_id,
                "vehicle_plate": vehicle_plate,
                "action_label": "View vehicle",
            },
        )

    # ─── COMMISSION ────────────────────────────────────────────────────────
    @staticmethod
    async def on_commission_accrued(
        db: AsyncSession,
        tenant_id: int,
        target_user_id: int,
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
            payload={
                "amount": amount,
                "booking_number": booking_number,
                "action_label": "View commission",
            },
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
                tenant_id=tenant_id,
                user_ids=super_admin_ids,
                type=NotificationType.payment,
                priority=NotificationPriority.normal,
                title="Commission Payment Submitted",
                message=f"A commission payment of {amount} (Ref: {reference}) is awaiting verification.",
                action_url=f"/super-admin/commission/payments?status=pending",
                payload={
                    "payment_id": payment_id,
                    "amount": amount,
                    "reference": reference,
                    "action_label": "Verify payment",
                },
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
            payload={
                "payment_id": payment_id,
                "amount": amount,
                "reference": reference,
                "action_label": "View commission",
            },
        )
