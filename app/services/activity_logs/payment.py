from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class PaymentActivityLogger:
    @staticmethod
    async def on_recorded(db: AsyncSession, tenant_id: int, user_id: int, payment, invoice_number: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="record_payment", target_type="payment", target_id=payment.id, details={"invoice_number": invoice_number, "amount": str(payment.amount), "method": payment.method.value, "currency": payment.currency_code, "reference": payment.reference})

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: int, payment, reason: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="void_payment", target_type="payment", target_id=payment.id, details={"amount": str(payment.amount), "reason": reason})
