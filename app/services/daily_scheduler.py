# app/services/daily_scheduler.py

from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskPriority
from app.models.users import User
from app.models.invoices import Invoice
from app.models.vehicles import Vehicle, VehicleStatus
from app.services.reconciliation import run_reconciliation_job
from app.services.task_core import TaskCoreService


class DailySchedulerService:
    """
    Runs daily (via Cron Job) to catch time-sensitive compliance and financial issues.
    Uses TaskCoreService to ensure Plan A / Plan B smart routing.
    """

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

        # =====================================================================
        # 4. ✅ FLEET OPS: Return mileage not yet logged (mileage_due flag)
        # =====================================================================
        # The lifecycle now keeps returned cars rentable and flags mileage_due.
        # This task prompts the operator to log the odometer so service
        # scheduling stays accurate. smart_create_task dedupes (no daily spam).
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

        # =====================================================================
        # 5. ✅ LIFECYCLE SAFETY NET: drift fix + signed auto-start retry
        # =====================================================================
        # Self-contained (own sessions, per-tenant). Fixes booking↔vehicle
        # drift, auto-starts signed-but-inactive trips, and flips overdue
        # invoice status. Conservative — anything uncertain is logged, not guessed.
        await run_reconciliation_job()
