import os
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import Contract, ContractStatus
from app.models.bookings import Booking
from app.services.number_generator import generate_contract_number

CONTRACTS_DIR = "storage/contracts"


def _ensure_dir():
    os.makedirs(CONTRACTS_DIR, exist_ok=True)


async def create_contract_for_booking(booking: Booking, db: AsyncSession) -> Contract:
    """✅ FAST PATH: create + commit the contract row and return immediately.

    PDF rendering (Chromium) is deliberately NOT awaited here — it can take
    30–90s on a cold Render instance and blocks the HTTP response, causing
    frontend timeouts while the backend "eventually" finishes.
    The PDF is rendered in the background (render_and_store_contract_pdf)
    and/or on demand by the download endpoint's existing fallback.
    """
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
    """✅ BACKGROUND WORKER: renders the PDF using its OWN db session.

    Safe to run after the response is sent (BackgroundTasks / create_task)
    because it never touches the request-scoped session.
    Idempotent: skips if the PDF already exists on disk.
    """
    # ✅ CORRECTED: uses AsyncSessionLocal from your database.py
    from app.db.database import AsyncSessionLocal
    from app.services.contract_pdf import generate_contract_pdf

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        if not contract:
            return
        if contract.pdf_path and os.path.exists(contract.pdf_path):
            return  # already rendered

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
            # Not fatal: the download endpoint regenerates on demand.
            print(f"❌ BACKGROUND PDF GENERATION FAILED (will retry on download): {e}")


def schedule_contract_pdf_render(contract_id: int) -> None:
    """Fire-and-forget helper for call sites that can't use BackgroundTasks."""
    try:
        asyncio.get_running_loop()
        asyncio.create_task(render_and_store_contract_pdf(contract_id))
    except RuntimeError:
        pass  # no running loop — download endpoint will render on demand
