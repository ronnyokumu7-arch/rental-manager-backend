"""
Pricing quote endpoints — live breakdown for booking forms.

✅ PHASE 1: pure self-drive pricing via pricing_selfdrive.quote_selfdrive.
   No DB writes, no config lookups, no legacy engine.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.commission_lock import require_not_commission_locked
from app.models.drivers import Driver
from app.models.users import User
from app.models.vehicles import Vehicle
from app.services.pricing_selfdrive import quote_selfdrive

router = APIRouter()


class SelfDriveQuoteRequest(BaseModel):
    """Request schema for self-drive quote."""
    vehicle_id: int
    pickup_at: datetime
    return_at: datetime
    daily_rate_override: Optional[Decimal] = Field(None, ge=0)
    driver_id: Optional[int] = None


class PricingLineOut(BaseModel):
    """Single line item."""
    description: str
    quantity: str
    amount: Decimal


class SelfDriveQuoteResponse(BaseModel):
    """Response schema for self-drive quote."""
    vehicle_id: int
    pickup_at: datetime
    return_at: datetime
    daily_rate: Decimal
    driver_daily_fee: Optional[Decimal]
    billable_days: int
    vehicle_subtotal: Decimal
    driver_subtotal: Decimal
    total: Decimal
    lines: list[PricingLineOut]


@router.post("/self-drive/quote", response_model=SelfDriveQuoteResponse)
@limiter.limit("60/minute")
async def quote_self_drive(
    request: Request,
    payload: SelfDriveQuoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    """
    Get live pricing breakdown for self-drive booking.
    
    Accepts optional daily_rate_override and driver_id.
    Returns full line-item breakdown for UI display.
    """
    # Load vehicle
    vehicle_stmt = select(Vehicle).where(
        Vehicle.id == payload.vehicle_id,
        Vehicle.tenant_id == current_user.tenant_id,
    )
    vehicle = (await db.execute(vehicle_stmt)).scalars().first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    
    # Use override or vehicle default
    daily_rate = payload.daily_rate_override or vehicle.daily_rate
    if not daily_rate or daily_rate <= 0:
        raise HTTPException(status_code=400, detail="Vehicle has no daily rate configured")
    
    # Load driver if assigned
    driver_daily_fee = None
    if payload.driver_id:
        driver_stmt = select(Driver).where(
            Driver.id == payload.driver_id,
            Driver.tenant_id == current_user.tenant_id,
        )
        driver = (await db.execute(driver_stmt)).scalars().first()
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found")
        driver_daily_fee = driver.daily_fee
    
    # Calculate quote
    quote = quote_selfdrive(
        pickup_at=payload.pickup_at,
        return_at=payload.return_at,
        daily_rate=Decimal(daily_rate),
        driver_daily_fee=Decimal(driver_daily_fee) if driver_daily_fee else None,
    )
    
    return SelfDriveQuoteResponse(
        vehicle_id=payload.vehicle_id,
        pickup_at=quote.pickup_at,
        return_at=quote.return_at,
        daily_rate=quote.daily_rate,
        driver_daily_fee=quote.driver_daily_fee,
        billable_days=quote.billable_days,
        vehicle_subtotal=quote.vehicle_subtotal,
        driver_subtotal=quote.driver_subtotal,
        total=quote.total,
        lines=[
            PricingLineOut(description=l.description, quantity=l.quantity, amount=l.amount)
            for l in quote.lines
        ],
    )
