from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking
from app.models.contracts import Contract
from app.models.users import User
from app.services.contracts import create_contract_for_booking
from app.services.cache import invalidate_booking_cache
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
    # ✅ FIX: Use correct helper signature (booking_id, user, db)
    booking = await get_authorized_booking_async(booking_id, current_user, db)
    
    # ✅ Safety Check: Prevent duplicate contracts (with tenant scoping for defense in depth)
    existing_stmt = select(Contract).where(
        Contract.booking_id == booking.id,
        Contract.tenant_id == current_user.tenant_id
    )
    existing_result = await db.execute(existing_stmt)
    existing_contract = existing_result.scalars().first()
    
    if existing_contract:
        return {
            "message": "Contract already exists for this booking",
            "contract_id": existing_contract.id,
            "contract_number": existing_contract.contract_number,
            "pdf_path": existing_contract.pdf_path
        }

    # Generate the contract (Service handles PDF generation safely with try/except)
    contract = await create_contract_for_booking(booking, db)
    
    # ✅ Invalidate booking cache in case the service updated any booking-related state
    await invalidate_booking_cache(current_user.tenant_id)
    
    return {
        "message": "Contract generated successfully",
        "contract_id": contract.id,
        "contract_number": contract.contract_number,
        "pdf_path": contract.pdf_path
    }
