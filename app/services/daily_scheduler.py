# app/services/daily_scheduler.py

from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskPriority
from app.models.users import User
from app.models.invoices import Invoice
from app.models.vehicles import Vehicle, VehicleStatus
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
        users_result = await db.execute(users_stmt)
        users_with_expiring_dl = users_result.scalars().all()

        for user in users_with_expiring_dl:
            # Handle both Date and DateTime types safely
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
                due_date=expiry_date - timedelta(days=2), # Due 2 days before actual expiry
                target_type="user", 
                target_id=user.id
            )

        # =====================================================================
        # 2. FINANCIAL HEALTH: Overdue Invoices
        # =====================================================================
        # We look for invoices that are 'sent' or 'overdue' and past their due date
        invoices_stmt = select(Invoice).where(
            Invoice.status.in_(["sent", "overdue"]), 
            Invoice.due_date < today
        )
        invoices_result = await db.execute(invoices_stmt)
        overdue_invoices = invoices_result.scalars().all()

        for invoice in overdue_invoices:
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
                due_date=today + timedelta(days=1), # Due tomorrow
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
        vehicles_result = await db.execute(vehicles_stmt)
        vehicles_with_expiring_insurance = vehicles_result.scalars().all()

        for vehicle in vehicles_with_expiring_insurance:
            expiry_date = vehicle.insurance_expiry.date() if hasattr(vehicle.insurance_expiry, 'date') else vehicle.insurance_expiry
            days_left = (expiry_date - today).days
            
            # Only trigger if expiring within the next 30 days (and not already expired, though expired is caught by < 0)
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
