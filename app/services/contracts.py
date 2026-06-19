import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.contracts import Contract, ContractStatus
from app.models.bookings import Booking
from app.models.tenant_profile import TenantProfile


CONTRACTS_DIR = "storage/contracts"


def _ensure_dir():
    os.makedirs(CONTRACTS_DIR, exist_ok=True)


def _generate_contract_number(tenant_id: int, db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.query(Contract).filter(Contract.tenant_id == tenant_id).count()
    sequence = str(count + 1).zfill(4)
    return f"T{tenant_id}-{year}-{sequence}"


def create_contract_for_booking(booking: Booking, db: Session) -> Contract:
    from app.services.pdf import generate_contract_pdf

    _ensure_dir()
    contract_number = _generate_contract_number(booking.tenant_id, db)

    contract = Contract(
        booking_id=booking.id,
        tenant_id=booking.tenant_id,
        contract_number=contract_number,
        status=ContractStatus.draft,
    )
    db.add(contract)
    db.flush()

    try:
        pdf_bytes = generate_contract_pdf(contract, db)
        filename = f"{contract_number}.pdf"
        filepath = os.path.join(CONTRACTS_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)
        contract.pdf_path = filepath
    except Exception as e:
        contract.pdf_path = None

    db.commit()
    db.refresh(contract)
    return contract