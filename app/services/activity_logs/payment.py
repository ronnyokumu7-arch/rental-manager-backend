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


class PaymentActivityLogger:
    """Activity logging helpers for payment-related actions."""

    @staticmethod
    async def on_recorded(db: AsyncSession, tenant_id: int, user_id: Optional[int], payment, invoice_number: str) -> None:
        """
        Log a payment record event.

        ✅ CRITICAL: Payment Received is High Priority (Revenue).
        ✅ SNAPSHOT: Captures client, amount, and reference for instant UI rendering.
        """
        # ✅ FIXED: Get client through invoice.booking.client chain
        client = _get_client(payment)
        summary = {
            "amount": f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else None,
            "reference": payment.reference,
            "invoice_number": invoice_number,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "method": payment.method.value if payment.method else None,
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
            details={
                "invoice_number": invoice_number,
                "amount": str(payment.amount),
                "method": payment.method.value if payment.method else None,
                "currency": payment.currency_code,
                "reference": payment.reference,
            },
            priority=3,  # High (Revenue)
        )

    @staticmethod
    async def on_failed(db: AsyncSession, tenant_id: int, user_id: Optional[int], payment, reason: str) -> None:
        """
        Log a payment failure event.

        ✅ CRITICAL: Failed payments are High Priority (Cash Flow Risk).
        """
        # ✅ FIXED: Get client through invoice.booking.client chain
        client = _get_client(payment)
        summary = {
            "amount": f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else None,
            "reference": payment.reference,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "reason": reason,
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
            details={
                "amount": str(payment.amount),
                "reason": reason,
                "reference": payment.reference,
            },
            priority=3,  # High (Cash Flow Risk)
        )

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: Optional[int], payment, reason: str) -> None:
        """
        Log a payment void event.
        """
        # ✅ FIXED: Get client through invoice.booking.client chain
        client = _get_client(payment)
        summary = {
            "amount": f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else None,
            "reference": payment.reference,
            "client_name": client.full_name if client else None,
            "client_phone": client.phone if client else None,
            "reason": reason,
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
            details={
                "amount": str(payment.amount),
                "reason": reason,
                "reference": payment.reference,
            },
            priority=3,  # High (Lost Revenue / Audit)
        )
