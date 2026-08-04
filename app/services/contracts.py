import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import Contract, ContractStatus
from app.models.bookings import Booking
from app.models.tenant_profile import TenantProfile
from app.services.number_generator import generate_contract_number  # ✅ NEW: Centralized number generator

CONTRACTS_DIR = "storage/contracts"


def _ensure_dir():
    os.makedirs(CONTRACTS_DIR, exist_ok=True)


async def create_contract_for_booking(booking: Booking, db: AsyncSession) -> Contract:
    from app.services.contract_pdf import generate_contract_pdf
    
    _ensure_dir()
    
    # ✅ Generate contract number (Centralized, tenant-scoped, monthly-resetting)
    # Format: C{YYYY}{MM}{###} (e.g., C202607001)
    contract_number = await generate_contract_number(db, booking.tenant_id)

    contract = Contract(
        booking_id=booking.id,
        tenant_id=booking.tenant_id,
        contract_number=contract_number,
        status=ContractStatus.draft,
    )
    db.add(contract)
    await db.flush()

    try:
        # ✅ AWAIT the async PDF generation
        pdf_bytes = await generate_contract_pdf(contract, db)
        filename = f"{contract_number}.pdf"
        filepath = os.path.join(CONTRACTS_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)
        contract.pdf_path = filepath
        print(f"✅ Contract PDF generated: {filepath}")
    except Exception as e:
        print(f"❌ CONTRACT PDF GENERATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        contract.pdf_path = None

    await db.commit()
    await db.refresh(contract)
    return contract
