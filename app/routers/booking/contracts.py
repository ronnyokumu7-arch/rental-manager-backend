# app/routers/booking/contracts.py
"""
✅ Manual contract generation for a booking.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ ENVELOPE: responses carry StandardResponse fields (type/title/message)
   layered over the existing data keys — frontend keeps working, toasts light up.

✅ AUDIT (Phase B):
  - NEW GUARD: cancelled bookings can't produce contracts (was silent).
  - Duplicate → type=warning (idempotent no-op, not a silent 200).
  - Success → type=success with clear next-step copy.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking, BookingStatus
from app.models.contracts import Contract
from app.models.users import User
from app.services.contracts import create_contract_for_booking
from app.services.cache import invalidate_booking_cache, invalidate_contract_cache  # ✅ ADD contract
from ._helpers import get_authorized_booking_async

router = APIRouter()


@router.post("/{booking_id}/generate-contract")
@limiter.limit("10/minute")
async def generate_contract_for_booking(
    request: Request,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually generate a contract for a booking.
    Gracefully handles cases where a contract already exists.
    """
    booking = await get_authorized_booking_async(booking_id, current_user, db)

    # ✅ NEW GUARD (Phase B audit): a cancelled booking produces no contract.
    if booking.status == BookingStatus.cancelled:
        raise ConflictError(
            title="Booking Cancelled",
            message="This booking was cancelled, so a contract can't be generated.",
        )

    # ✅ Safety Check: Prevent duplicate contracts (tenant-scoped)
    existing_stmt = select(Contract).where(
        Contract.booking_id == booking.id,
        Contract.tenant_id == current_user.tenant_id
    )
    existing_result = await db.execute(existing_stmt)
    existing_contract = existing_result.scalars().first()

    if existing_contract:
        # ✅ Phase B: idempotent no-op → warning envelope (old keys preserved)
        return {
            "type": "warning",
            "title": "Contract Already Exists",
            "message": "This booking already has a contract. The existing one is shown below.",
            "contract_id": existing_contract.id,
            "contract_number": existing_contract.contract_number,
            "pdf_path": existing_contract.pdf_path
        }

    contract = await create_contract_for_booking(booking, db)

    # ✅ Invalidate BOTH caches so the new contract appears instantly
    await invalidate_booking_cache(current_user.tenant_id)
    await invalidate_contract_cache(current_user.tenant_id)   # ✅ ADD

    # ✅ Phase B: success envelope (old keys preserved)
    return {
        "type": "success",
        "title": "Contract Ready",
        "message": "The contract is ready to review and send to the client.",
        "contract_id": contract.id,
        "contract_number": contract.contract_number,
        "pdf_path": contract.pdf_path
    }
