"""
Contract creation for bookings.

✅ LIFECYCLE:
  - ensure_contract_for_booking → auto-called on confirm (idempotent, flush-only,
    caller commits atomically). Background PDF render + auto-send are scheduled
    by the confirm flow / reconciliation job.
  - create_contract_for_booking → manual path (commits on its own).
"""
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contracts import Contract, ContractStatus
from app.models.bookings import Booking
from app.services.number_generator import generate_contract_number

CONTRACTS_DIR = "storage/contracts"


def _ensure_dir():
    os.makedirs(CONTRACTS_DIR, exist_ok=True)


# =============================================================================
# ✅ LIFECYCLE: idempotent lookup + flush-only create (caller commits)
# =============================================================================
async def get_booking_contract(db: AsyncSession, booking_id: int) -> Optional[Contract]:
    """Return the booking's contract (latest), if any."""
    stmt = (
        select(Contract)
        .where(Contract.booking_id == booking_id)
        .order_by(Contract.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def ensure_contract_for_booking(booking: Booking, db: AsyncSession) -> Contract:
    """
    ✅ AUTO-CALLED on confirm. Creates the contract if none exists (idempotent).

    - FLUSH only — the caller (confirm flow) commits atomically with the
      booking status change.
    - Returns the existing contract if one already exists (no duplicates).
    """
    existing = await get_booking_contract(db, booking.id)
    if existing:
        return existing

    contract_number = await generate_contract_number(db, booking.tenant_id)
    contract = Contract(
        booking_id=booking.id,
        tenant_id=booking.tenant_id,
        contract_number=contract_number,
        status=ContractStatus.draft,
    )
    db.add(contract)
    await db.flush()      # caller commits
    return contract


# =============================================================================
# EXISTING: manual creation (commits on its own)
# =============================================================================
async def create_contract_for_booking(booking: Booking, db: AsyncSession) -> Contract:
    """Create contract row instantly - NO PDF generation."""
    _ensure_dir()

    contract_number = await generate_contract_number(db, booking.tenant_id)

    contract = Contract(
        booking_id=booking.id,
        tenant_id=booking.tenant_id,
        contract_number=contract_number,
        status=ContractStatus.draft,
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return contract


async def render_and_store_contract_pdf(contract_id: int) -> None:
    """Background PDF renderer - uses its own DB session."""
    from app.db.database import AsyncSessionLocal
    from app.services.contract_pdf import generate_contract_pdf

    async with AsyncSessionLocal() as db:
        # ✅ FIXED: Eager-load booking/client/vehicle — generate_contract_pdf needs them.
        stmt = select(Contract).options(
            selectinload(Contract.booking).selectinload(Booking.client),
            selectinload(Contract.booking).selectinload(Booking.vehicle),
        ).where(Contract.id == contract_id)
        result = await db.execute(stmt)
        contract = result.scalars().unique().first()

        if not contract:
            return

        # Skip if already rendered
        if contract.pdf_path and os.path.exists(contract.pdf_path):
            return

        try:
            _ensure_dir()
            pdf_bytes = await generate_contract_pdf(contract, db)
            filepath = os.path.join(CONTRACTS_DIR, f"{contract.contract_number}.pdf")
            with open(filepath, "wb") as f:
                f.write(pdf_bytes)

            contract.pdf_path = filepath
            await db.commit()
            print(f"✅ Contract PDF generated (background): {filepath}")
        except Exception as e:
            await db.rollback()
            print(f"❌ Background PDF generation failed: {e}")


async def regenerate_contract_for_booking(
    booking_id: int,
    tenant_id: int,
    db: AsyncSession
) -> Contract:
    """Delete existing contract (any status) and create a new one."""
    existing_stmt = select(Contract).where(
        Contract.booking_id == booking_id,
        Contract.tenant_id == tenant_id
    )
    existing = (await db.execute(existing_stmt)).scalars().first()

    if existing:
        if existing.pdf_path and os.path.exists(existing.pdf_path):
            try:
                os.remove(existing.pdf_path)
            except OSError:
                pass

        await db.delete(existing)
        await db.commit()

    booking_stmt = select(Booking).where(
        Booking.id == booking_id,
        Booking.tenant_id == tenant_id
    )
    booking = (await db.execute(booking_stmt)).scalars().first()

    if not booking:
        raise ValueError(f"Booking {booking_id} not found")

    return await create_contract_for_booking(booking, db)
