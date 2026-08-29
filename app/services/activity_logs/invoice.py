# app/services/activity_logs/invoice.py

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


class InvoiceActivityLogger:
    """Activity logging helpers for invoice-related actions."""

    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: Optional[int], invoice) -> None:
        """
        Log an invoice creation event.
        """
        client = _rel(invoice, "client")
        summary = {
            "invoice_number": invoice.invoice_number,
            "amount_due": f"{invoice.currency_code} {invoice.amount_due:,.2f}" if invoice.amount_due else None,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="create_invoice",
            label="Invoice Created",
            target_type="invoice",
            target_id=invoice.id,
            summary=summary,
            details={
                "invoice_number": invoice.invoice_number,
                "amount_due": str(invoice.amount_due),
                "currency": invoice.currency_code,
            },
            priority=2,  # Normal
        )

    @staticmethod
    async def on_paid(db: AsyncSession, tenant_id: int, user_id: Optional[int], invoice) -> None:
        """
        Log an invoice paid event.

        ✅ CRITICAL: Paid invoices are High Priority (Revenue).
        """
        client = _rel(invoice, "client")
        summary = {
            "invoice_number": invoice.invoice_number,
            "amount_due": f"{invoice.currency_code} {invoice.amount_due:,.2f}" if invoice.amount_due else None,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "payment_reference": invoice.payment_reference if hasattr(invoice, "payment_reference") else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="invoice_paid",
            label="Invoice Paid",
            target_type="invoice",
            target_id=invoice.id,
            summary=summary,
            details={
                "invoice_number": invoice.invoice_number,
                "amount_paid": str(invoice.amount_due),
                "payment_reference": invoice.payment_reference if hasattr(invoice, "payment_reference") else None,
            },
            priority=3,  # High (Revenue)
        )

    @staticmethod
    async def on_overdue(db: AsyncSession, tenant_id: int, user_id: Optional[int], invoice) -> None:
        """
        Log an invoice overdue event.

        ✅ CRITICAL: Overdue invoices are High Priority (Cash Flow Risk).
        """
        client = _rel(invoice, "client")
        summary = {
            "invoice_number": invoice.invoice_number,
            "amount_due": f"{invoice.currency_code} {invoice.amount_due:,.2f}" if invoice.amount_due else None,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "days_overdue": invoice.days_overdue if hasattr(invoice, "days_overdue") else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="invoice_overdue",
            label="Invoice Overdue",
            target_type="invoice",
            target_id=invoice.id,
            summary=summary,
            details={
                "invoice_number": invoice.invoice_number,
                "amount_due": str(invoice.amount_due),
                "days_overdue": invoice.days_overdue if hasattr(invoice, "days_overdue") else None,
            },
            priority=3,  # High (Cash Flow Risk)
        )

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: Optional[int], invoice) -> None:
        """
        Log an invoice void event.
        """
        client = _rel(invoice, "client")
        summary = {
            "invoice_number": invoice.invoice_number,
            "amount_due": f"{invoice.currency_code} {invoice.amount_due:,.2f}" if invoice.amount_due else None,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="void_invoice",
            label="Invoice Voided",
            target_type="invoice",
            target_id=invoice.id,
            summary=summary,
            details={
                "invoice_number": invoice.invoice_number,
                "amount_due": str(invoice.amount_due),
            },
            priority=3,  # High (Lost Revenue)
        )
