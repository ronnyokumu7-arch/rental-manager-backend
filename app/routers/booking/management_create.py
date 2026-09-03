# app/routers/booking/management_create.py
"""
✅ CREATE + QUOTE — CONTRACT v2: thin handlers over the booking factory.

  POST /quote  → truthful live preview for the unified datetime control
  POST /       → create (factory owns schedule, conflicts, pricing, quotation,
                 tasks, activity logs, cache invalidation — one atomic commit)

Pricing rule (untouched): vehicle rate × billable days via the pure engines.
All datetimes flow through app/core/timeutils.py (aware-only, naive→EAT,
defaults pickup=now / return=+1d, 2-min past grace, "now" allowed).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.commission_lock import require_not_commission_locked
from app.models.drivers import Driver
from app.models.users import User
from app.schemas.booking import (
    BookingCreate,
    BookingOut,
    BookingQuote,
    BookingQuoteOut,
)
from app.services import booking_factory

router = APIRouter()


# ---------------------------------------------------------------------------
# ✅ Back-compat shim: lifecycle/other modules import this name from here.
#    The real logic lives in the factory — single source of truth.
# ---------------------------------------------------------------------------
async def validate_driver_assignment(
    db: AsyncSession, tenant_id: int, driver_id: int,
) -> Driver:
    driver = await booking_factory.load_driver_assignment(db, tenant_id, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found.")
    return driver


# ---------------------------------------------------------------------------
# QUOTE (dry-run) — the unified datetime control calls this on every change
# ---------------------------------------------------------------------------
@router.post("/quote", response_model=BookingQuoteOut)
@limiter.limit("30/minute")
async def quote_booking(
    request: Request,
    quote: BookingQuote,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    """Defaults: pickup = now, return = +1 day. Conflict-checked. rate × days."""
    return await booking_factory.quote_new(
        db,
        tenant_id=current_user.tenant_id,
        vehicle_id=quote.vehicle_id,
        pickup_raw=quote.pickup_at,
        return_raw=quote.return_at,
        service_type=quote.service_type,
        driver_id=quote.driver_id,
        service_details=quote.service_details,
        toll_fees=quote.toll_fees,
        parking_fees=quote.parking_fees,
    )


# ---------------------------------------------------------------------------
# CREATE — thin handler; the factory owns everything
# ---------------------------------------------------------------------------
@router.post("/", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_booking(
    request: Request,
    booking: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
):
    """
    ✅ QUOTATION PIPELINE preserved: the factory creates the booking together
    with its quotation (doc_type=quotation, status=sent, share_token ready)
    in ONE atomic commit. Client accepts on the public page → morph to
    invoice + pending→confirmed.
    """
    return await booking_factory.create_booking(db, booking, current_user)
