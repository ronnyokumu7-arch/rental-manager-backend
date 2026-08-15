# app/services/contracts.py
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contracts import Contract, ContractStatus
from app.models.bookings import Booking
from app.services.number_generator import generate_contract_number

CONTRACTS_DIR = "storage/contracts"


def _ensure_dir():
    os.makedirs(CONTRACTS_DIR, exist_ok=True)


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
        # Without this, async lazy-loading raises MissingGreenlet and the render dies silently.
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
    # ✅ FIXED: `select` is now imported (was NameError before)
    existing_stmt = select(Contract).where(
        Contract.booking_id == booking_id,
        Contract.tenant_id == tenant_id
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalars().first()

    if existing:
        # Delete the old PDF file if it exists
        if existing.pdf_path and os.path.exists(existing.pdf_path):
            try:
                os.remove(existing.pdf_path)
            except OSError:
                pass

        await db.delete(existing)
        await db.commit()

    # Fetch the booking
    booking_stmt = select(Booking).where(
        Booking.id == booking_id,
        Booking.tenant_id == tenant_id
    )
    booking_result = await db.execute(booking_stmt)
    booking = booking_result.scalars().first()

    if not booking:
        raise ValueError(f"Booking {booking_id} not found")

    # Create new contract
    return await create_contract_for_booking(booking, db)
