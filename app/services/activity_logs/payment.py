# app/services/activity_logs/payment.py

from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService


class PaymentActivityLogger:
    """Activity logging helpers for payment-related actions."""

    @staticmethod
    async def on_recorded(db: AsyncSession, tenant_id: int, user_id: int, payment, invoice_number: str) -> None:
        """
        Log a payment record event.

        ✅ CRITICAL: Payment Received is High Priority (Revenue).
        ✅ SNAPSHOT: Captures client, amount, and reference for instant UI rendering.
        """
        # ✅ Build the denormalized summary snapshot
        summary = {
            "amount": f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else None,
            "reference": payment.reference,
            "invoice_number": invoice_number,
            "client_name": getattr(payment.client, "full_name", None) if payment.client else None,
            "client_phone": getattr(payment.client, "phone", None) if payment.client else None,
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
    async def on_failed(db: AsyncSession, tenant_id: int, user_id: int, payment, reason: str) -> None:
        """
        Log a payment failure event.

        ✅ CRITICAL: Failed payments are High Priority (Cash Flow Risk).
        """
        summary = {
            "amount": f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else None,
            "reference": payment.reference,
            "client_name": getattr(payment.client, "full_name", None) if payment.client else None,
            "client_phone": getattr(payment.client, "phone", None) if payment.client else None,
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
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: int, payment, reason: str) -> None:
        """
        Log a payment void event.
        """
        summary = {
            "amount": f"{payment.currency_code} {payment.amount:,.2f}" if payment.amount else None,
            "reference": payment.reference,
            "client_name": getattr(payment.client, "full_name", None) if payment.client else None,
            "client_phone": getattr(payment.client, "phone", None) if payment.client else None,
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
