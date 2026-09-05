# app/services/daily_scheduler.py

from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityLog
from app.models.task import TaskPriority
from app.models.users import User
from app.models.bookings import Booking, BookingStatus
from app.models.invoices import Invoice
from app.models.vehicles import Vehicle, VehicleStatus
from app.services.reconciliation import run_reconciliation_job
from app.services.task_core import TaskCoreService
from app.services.activity_logs.service import ActivityLogService  # ✅ NEW
from app.services.activity_logs.vehicle import VehicleActivityLogger  # ✅ NEW
from app.services.activity_logs.booking import BookingActivityLogger  # ✅ NEW


async def _logged_today(db: AsyncSession, tenant_id: int, action: str, target_id: int) -> bool:
    """✅ Once-per-day dedup: skip recurring alerts already logged today."""
    start = datetime.combine(datetime.now().date(), datetime.min.time())
    stmt = select(ActivityLog.id).where(
        ActivityLog.tenant_id == tenant_id,
        ActivityLog.action == action,
        ActivityLog.target_id == target_id,
        ActivityLog.created_at >= start,
    )
    return (await db.execute(stmt)).scalars().first() is not None


class DailySchedulerService:
    """
    Runs daily (via Cron Job) to catch time-sensitive compliance and financial issues.
    Uses TaskCoreService to ensure Plan A / Plan B smart routing.
    """

    @staticmethod
    async def run_frequent_autostart():
        """
        ✅ Runs every few minutes (in-app loop / frequent cron) — NOT daily.
        Starts signed trips whose pickup has arrived, fixes drift, marks overdue.
        Lightweight + idempotent; safe to run frequently.
        """
        await run_reconciliation_job()

    @staticmethod
    async def run_daily_checks(db: AsyncSession):
        """Main entry point for the daily cron job."""
        today = datetime.now().date()

        # =====================================================================
        # 1. STAFF COMPLIANCE: Expiring Driver's Licenses
        # =====================================================================
        users_stmt = select(User).where(
            User.dl_expiry != None,
            User.dl_expiry.between(today, today + timedelta(days=30)),
            User.is_active == True,
            User.tenant_id != None
        )
        for user in (await db.execute(users_stmt)).scalars().all():
            expiry_date = user.dl_expiry.date() if hasattr(user.dl_expiry, 'date') else user.dl_expiry
            days_left = (expiry_date - today).days

            await TaskCoreService.smart_create_task(
                db=db,
                tenant_id=user.tenant_id,
                target_role="HR",
                title=f"Renew Driver's License ({user.full_name})",
                description=f"Staff member {user.full_name}'s Driver's License expires in {days_left} days ({expiry_date}). Please initiate the renewal process.",
                category="compliance",
                priority=TaskPriority.high if days_left < 7 else TaskPriority.medium,
                due_date=expiry_date - timedelta(days=2),
                target_type="user",
                target_id=user.id
            )

            # ✅ System alert (actor=None; subject is the target), once per day
            if not await _logged_today(db, user.tenant_id, "dl_expired", user.id):
                await ActivityLogService.log(
                    db=db,
                    tenant_id=user.tenant_id,
                    user_id=None,
                    action="dl_expired",
                    label="Driver's License Expiring",
                    target_type="user",
                    target_id=user.id,
                    summary={
                        "driver_name": user.full_name,
                        "days_left": days_left,
                        "expiry_date": expiry_date.isoformat() if expiry_date else None,
                    },
                    priority=3 if days_left < 7 else 2,
                )

        # =====================================================================
        # 2. FINANCIAL HEALTH: Overdue Invoices
        # =====================================================================
        invoices_stmt = select(Invoice).where(
            Invoice.status.in_(["sent", "overdue"]),
            Invoice.due_date < today
        )
        for invoice in (await db.execute(invoices_stmt)).scalars().all():
            due_date = invoice.due_date.date() if hasattr(invoice.due_date, 'date') else invoice.due_date
            days_overdue = (today - due_date).days

            amount = getattr(invoice, 'total_amount', getattr(invoice, 'amount_due', 'N/A'))
            inv_number = getattr(invoice, 'invoice_number', getattr(invoice, 'id', 'Unknown'))

            await TaskCoreService.smart_create_task(
                db=db,
                tenant_id=invoice.tenant_id,
                target_role="Accountant",
                title=f"Follow up on Overdue Invoice #{inv_number}",
                description=f"Invoice #{inv_number} is {days_overdue} days overdue (Due: {due_date}). Amount due: {amount}. Please contact the client for payment.",
                category="finance",
                priority=TaskPriority.urgent if days_overdue > 14 else TaskPriority.high,
                due_date=today + timedelta(days=1),
                target_type="invoice",
                target_id=invoice.id
            )

            # ✅ System alert, once per day
            if not await _logged_today(db, invoice.tenant_id, "invoice_overdue", invoice.id):
                await ActivityLogService.log(
                    db=db,
                    tenant_id=invoice.tenant_id,
                    user_id=None,
                    action="invoice_overdue",
                    label="Invoice Overdue",
                    target_type="invoice",
                    target_id=invoice.id,
                    summary={
                        "invoice_number": inv_number,
                        "amount": str(amount),
                        "days_overdue": days_overdue,
                    },
                    priority=3 if days_overdue > 14 else 2,
                )

        # =====================================================================
        # 3. FLEET COMPLIANCE: Expiring Vehicle Insurance
        # =====================================================================
        vehicles_stmt = select(Vehicle).where(
            Vehicle.insurance_expiry != None,
            Vehicle.status != VehicleStatus.retired,
            Vehicle.tenant_id != None
        )
        for vehicle in (await db.execute(vehicles_stmt)).scalars().all():
            expiry_date = vehicle.insurance_expiry.date() if hasattr(vehicle.insurance_expiry, 'date') else vehicle.insurance_expiry
            days_left = (expiry_date - today).days

            if days_left <= 30:
                status_text = f"OVERDUE by {abs(days_left)} days" if days_left < 0 else f"expires in {days_left} days"

                await TaskCoreService.smart_create_task(
                    db=db,
                    tenant_id=vehicle.tenant_id,
                    target_role="Fleet Manager",
                    title=f"Renew Insurance for {vehicle.plate_number}",
                    description=f"Vehicle {vehicle.plate_number} insurance {status_text} (Expiry: {expiry_date}). Contact the insurer to renew the policy immediately.",
                    category="compliance",
                    priority=TaskPriority.urgent if days_left < 0 else (TaskPriority.high if days_left < 7 else TaskPriority.medium),
                    due_date=expiry_date - timedelta(days=2),
                    target_type="vehicle",
                    target_id=vehicle.id
                )

                # ✅ System alert, once per day
                if not await _logged_today(db, vehicle.tenant_id, "vehicle_insurance_expiring", vehicle.id):
                    await ActivityLogService.log(
                        db=db,
                        tenant_id=vehicle.tenant_id,
                        user_id=None,  # System generated
                        action="vehicle_insurance_expiring",
                        label="Vehicle Insurance Expiring",
                        target_type="vehicle",
                        target_id=vehicle.id,
                        summary={
                            "vehicle_name": f"{vehicle.make} {vehicle.model}",
                            "plate_number": vehicle.plate_number,
                            "days_left": days_left,
                        },
                        priority=3 if days_left < 7 else 2,
                    )

        # =====================================================================
        # 4. ✅ FLEET OPS: Return mileage not yet logged (mileage_due flag)
        # =====================================================================
        mileage_stmt = select(Vehicle).where(
            Vehicle.mileage_due == True,
            Vehicle.status != VehicleStatus.retired,
            Vehicle.tenant_id != None
        )
        for vehicle in (await db.execute(mileage_stmt)).scalars().all():
            await TaskCoreService.smart_create_task(
                db=db,
                tenant_id=vehicle.tenant_id,
                target_role="Fleet Manager",
                title=f"Log return mileage for {vehicle.plate_number}",
                description=f"Vehicle {vehicle.plate_number} has returned from a trip but its return odometer reading hasn't been logged. Record it to keep service scheduling accurate.",
                category="compliance",
                priority=TaskPriority.medium,
                due_date=today + timedelta(days=1),
                target_type="vehicle",
                target_id=vehicle.id
            )

            # ✅ FIXED: on_mileage_due now exists on VehicleActivityLogger; once per day
            if not await _logged_today(db, vehicle.tenant_id, "mileage_due", vehicle.id):
                await VehicleActivityLogger.on_mileage_due(
                    db=db,
                    tenant_id=vehicle.tenant_id,
                    user_id=None,
                    vehicle=vehicle,
                )

        # =====================================================================
        # 5. ✅ LIFECYCLE SAFETY NET: Trip Overdue / Ending Today
        # =====================================================================
        bookings_stmt = (
            select(Booking)
            .options(
                selectinload(Booking.client),   # ✅ rich summaries (safe _rel reads)
                selectinload(Booking.vehicle),
            )
            .where(
                Booking.status == BookingStatus.active,
                Booking.end_date != None,
            )
        )
        for booking in (await db.execute(bookings_stmt)).scalars().all():
            end_date = booking.end_date.date() if hasattr(booking.end_date, 'date') else booking.end_date

            # ✅ Trip Ending Today (once per day)
            if end_date == today and not await _logged_today(db, booking.tenant_id, "trip_ending_today", booking.id):
                await BookingActivityLogger.on_trip_ending_today(
                    db=db,
                    tenant_id=booking.tenant_id,
                    user_id=None,  # system safety net
                    booking=booking,
                )

            # ✅ Trip Overdue (once per day — no feed flooding)
            if end_date < today and not await _logged_today(db, booking.tenant_id, "trip_overdue", booking.id):
                await BookingActivityLogger.on_trip_overdue(
                    db=db,
                    tenant_id=booking.tenant_id,
                    user_id=None,  # system safety net
                    booking=booking,
                )

        # =====================================================================
        # 6. ✅ LIFECYCLE SAFETY NET: drift fix + signed auto-start retry
        # =====================================================================
        await run_reconciliation_job()
