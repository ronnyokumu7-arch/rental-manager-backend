import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.services.invoices import create_invoice_for_booking
from app.services.cache import invalidate_booking_cache
from ._helpers import get_authorized_booking_async

router = APIRouter()

settings = get_settings()


# ✅ Optional payload for customizing the generated invoice
class GenerateInvoicePayload(BaseModel):
    custom_amount: Optional[Decimal] = Field(
        default=None, 
        gt=0, 
        decimal_places=2,
        description="Optional custom amount for the invoice"
    )
    custom_rate: Optional[Decimal] = Field(
        default=None, 
        gt=0, 
        decimal_places=2,
        description="Optional daily rate override — written to booking.daily_rate, recomputes total"
    )
    due_date: Optional[datetime] = Field(
        default=None, 
        description="Optional due date (today or later)"
    )
    notes: Optional[str] = Field(
        default=None, 
        max_length=1000, 
        description="Optional notes for the invoice"
    )


@router.post("/{booking_id}/generate-invoice")
@limiter.limit("10/minute")
async def generate_invoice(
    request: Request,
    booking_id: int,
    payload: Optional[GenerateInvoicePayload] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ✅ FIX: Use correct helper signature (booking_id, user, db)
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    # ✅ Validate due_date ONLY when provided (payload body is optional).
    # Due date is a calendar day — today is valid (pay-on-delivery, same-day
    # settlements). Only past days are rejected.
    if payload and payload.due_date:
        if payload.due_date.date() < datetime.now(timezone.utc).date():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Due date cannot be in the past."
            )

    # ✅ Pass customizations (including rate override) to the robust service
    invoice = await create_invoice_for_booking(
        booking, 
        db, 
        custom_amount=payload.custom_amount if payload else None, 
        custom_rate=payload.custom_rate if payload else None,
        due_date_override=payload.due_date if payload else None,
        notes=payload.notes if payload else None
    )
    
    # ✅ Ensure share token exists and is valid (7-day expiry)
    now = datetime.now(timezone.utc)
    if not invoice.share_token or (invoice.share_token_expires_at and invoice.share_token_expires_at < now):
        invoice.share_token = str(uuid.uuid4())
        invoice.share_token_expires_at = now + timedelta(days=7)
        await db.commit()
        await db.refresh(invoice)
        
    # ✅ Use settings.frontend_url instead of os.getenv for consistency
    base_url = settings.frontend_url.rstrip("/")
    
    # ✅ Invalidate booking cache in case the service updated any booking-related state
    await invalidate_booking_cache(current_user.tenant_id)
    
    return {
        "share_url": f"{base_url}/invoice/{invoice.share_token}",
        "token": invoice.share_token,
        "expires_at": invoice.share_token_expires_at.isoformat() if invoice.share_token_expires_at else None
    }