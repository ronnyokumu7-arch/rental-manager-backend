# app/routers/payment/_helpers.py
"""
✅ Shared tenant-isolation guards for payment endpoints.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ SECURITY: the 404 copy intentionally conflates "not found" and "no access"
   to prevent payment-ID enumeration — preserved as-is.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, NotFoundError
from app.models.payments import Payment
from app.models.users import User, UserRole


def get_authorized_payment(payment_id: int, user: User, db: Session) -> Payment:
    """Synchronous helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Payment).where(Payment.id == payment_id)
    else:
        if user.tenant_id is None:
            raise AuthorizationError(
                title="No Agency Linked",
                message="Your account isn't linked to an agency. Contact your administrator for access.",
            )
        stmt = select(Payment).where(
            Payment.id == payment_id,
            Payment.tenant_id == user.tenant_id
        )
    
    result = db.execute(stmt)
    payment = result.scalars().first()
    if not payment:
        raise NotFoundError(
            title="Payment Not Found",
            message="We couldn't find this payment, or you may not have access to it.",
        )
    return payment


async def get_authorized_payment_async(payment_id: int, user: User, db: AsyncSession) -> Payment:
    """Async helper with Super Admin bypass."""
    if user.role == UserRole.super_admin:
        stmt = select(Payment).where(Payment.id == payment_id)
    else:
        if user.tenant_id is None:
            raise AuthorizationError(
                title="No Agency Linked",
                message="Your account isn't linked to an agency. Contact your administrator for access.",
            )
        stmt = select(Payment).where(
            Payment.id == payment_id,
            Payment.tenant_id == user.tenant_id
        )
    
    result = await db.execute(stmt)
    payment = result.scalars().first()
    if not payment:
        raise NotFoundError(
            title="Payment Not Found",
            message="We couldn't find this payment, or you may not have access to it.",
        )
    return payment
