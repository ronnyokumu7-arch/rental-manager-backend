# app/services/activity_logs/payment.py

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


def _get_client(payment):
    """
    ✅ SAFELY extract client from payment.invoice.booking.client chain.
    """
    invoice = _rel(payment, "invoice")
    if not invoice:
        return None
    booking = _rel(invoice, "booking")
    if not booking:
        return None
    return _rel(booking, "client")


def _money(payment) -> str:
    return f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else ""


def _parts(payment, client, invoice_number: Optional[str]):
    """Builds the safe, intentional copy fragments (no 'None' leakage)."""
    who = client.full_name if client else None
    via = f" via {payment.method.value}" if payment.method else ""
    ref = f" (Ref {payment.reference})" if payment.reference else ""
    inv = f" on invoice {invoice_number}" if invoice_number else ""
    return who, _money(payment), via, ref, inv


class PaymentActivityLogger:
    """Activity logging helpers for payment-related actions."""

    @staticmethod
    async def on_submitted(
        db: AsyncSession,
        tenant_id: int,
        user_id: Optional[int],
        payment,
        invoice_number: str,
    ) -> None:
        """Pending / public-reported payment awaiting agency confirmation."""
        client = _get_client(payment)
        who, money, via, ref, inv = _parts(payment, client, invoice_number)
        subject = who or "A client"
        headline = f"{subject} submitted {money}{via}{ref}{inv} — awaiting confirmation."
        summary = {
            "headline": headline,
            "action_label": "Confirm payment received",
            "amount": money or None,
            "reference": payment.reference,
            "invoice_number": invoice_number,
            "client_name": who,
            "client_phone": client.phone if client else None,
            "method": payment.method.value if payment.method else None,
            "status": "pending",
        }
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="payment_submitted",
            label="Incoming Payment",
            target_type="payment",
            target_id=payment.id,
            summary=summary,
            details={**summary, "amount": str(payment.amount)},
            priority=3,  # High (Revenue pending confirmation)
        )

    @staticmethod
    async def on_recorded(db: AsyncSession, tenant_id: int, user_id: Optional[int], payment, invoice_number: str) -> None:
        """Confirmed / manual-offline payment recorded."""
        client = _get_client(payment)
        who, money, via, ref, inv = _parts(payment, client, invoice_number)
        headline = (
            f"{who} paid {money}{via}{ref}{inv}."
            if who
            else f"Payment of {money}{ref}{inv} recorded."
        )
        summary = {
            "headline": headline,
            "action_label": "View payment",
            "amount": money or None,
            "reference": payment.reference,
            "invoice_number": invoice_number,
            "client_name": who,
            "client_phone": client.phone if client else None,
            "method": payment.method.value if payment.method else None,
            "status": "completed",
        }
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="payment_received",  # ✅ Aligned with frontend mapper
            label="Payment Received",
            target_type="payment",
            target_id=payment.id,
            summary=summary,
            details={**summary, "amount": str(payment.amount)},
            priority=3,  # High (Revenue)
        )

    @staticmethod
    async def on_failed(db: AsyncSession, tenant_id: int, user_id: Optional[int], payment, reason: str, invoice_number: str = None) -> None:
        """Payment failed — names client, amount, ref, invoice, and reason."""
        client = _get_client(payment)
        who, money, via, ref, inv = _parts(payment, client, invoice_number)
        headline = (
            f"{who}'s {money} payment{ref}{inv} failed: {reason}."
            if who
            else f"{money} payment{ref}{inv} failed: {reason}."
        )
        summary = {
            "headline": headline,
            "amount": money or None,
            "reference": payment.reference,
            "invoice_number": invoice_number,
            "client_name": who,
            "client_phone": client.phone if client else None,
            "reason": reason,
            "status": "failed",
        }
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="payment_failed",  # ✅ Aligned with frontend mapper
            label="Payment Failed",
            target_type="payment",
            target_id=payment.id,
            summary=summary,
            details={**summary, "amount": str(payment.amount)},
            priority=3,  # High (Cash Flow Risk)
        )

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: Optional[int], payment, reason: str, invoice_number: str = None) -> None:
        """Payment voided — names client, amount, ref, invoice, and reason."""
        client = _get_client(payment)
        who, money, via, ref, inv = _parts(payment, client, invoice_number)
        for_part = f" for {who}" if who else ""
        headline = f"{money} payment{ref}{for_part}{inv} voided: {reason}."
        summary = {
            "headline": headline,
            "amount": money or None,
            "reference": payment.reference,
            "invoice_number": invoice_number,
            "client_name": who,
            "client_phone": client.phone if client else None,
            "reason": reason,
            "status": "void",
        }
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="void_payment",
            label="Payment Voided",
            target_type="payment",
            target_id=payment.id,
            summary=summary,
            details={**summary, "amount": str(payment.amount)},
            priority=3,  # High (Lost Revenue / Audit)
        )
