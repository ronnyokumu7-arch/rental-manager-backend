from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.payments import Payment
from app.models.users import User, UserRole


def get_authorized_payment(payment_id: int, user: User, db: Session) -> Payment:
    """Synchronous helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Payment).where(Payment.id == payment_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Payment).where(
            Payment.id == payment_id,
            Payment.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    payment = result.scalars().first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found or access denied"
        )
    return payment


async def get_authorized_payment_async(payment_id: int, user: User, db: AsyncSession) -> Payment:
    """Async helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Payment).where(Payment.id == payment_id)
    else:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )
        stmt = select(Payment).where(
            Payment.id == payment_id,
            Payment.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    payment = result.scalars().first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found or access denied"
        )
    return payment
