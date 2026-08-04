# app/services/activity_logs/invoice.py

from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class InvoiceActivityLogger:
    """Activity logging helpers for invoice-related actions."""

    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: int, invoice) -> None:
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="create_invoice",
            target_type="invoice",
            target_id=invoice.id,
            details={
                "invoice_number": invoice.invoice_number,
                "amount_due": str(invoice.amount_due),
                "currency": invoice.currency_code,
            },
        )

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: int, invoice) -> None:
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="void_invoice",
            target_type="invoice",
            target_id=invoice.id,
            details={
                "invoice_number": invoice.invoice_number,
                "amount_due": str(invoice.amount_due),
            },
        )
