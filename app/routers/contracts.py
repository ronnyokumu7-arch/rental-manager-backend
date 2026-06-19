from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.contracts import Contract, ContractStatus
from app.models.users import User
from app.schemas.contract import ContractOut
from app.services.contracts import create_contract_for_booking
from app.services.pdf import generate_contract_pdf


router = APIRouter(prefix="/contracts", tags=["contracts"])


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_contract_or_404(contract_id: int, tenant_id: int, db: Session) -> Contract:
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.tenant_id == tenant_id,
    ).first()
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Contract not found"
        )
    return contract


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ContractOut])
def list_contracts(
    booking_id: int | None = None,
    contract_status: ContractStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Contract).filter(Contract.tenant_id == current_user.tenant_id)
    if booking_id is not None:
        query = query.filter(Contract.booking_id == booking_id)
    if contract_status is not None:
        query = query.filter(Contract.status == contract_status)
    return query.order_by(Contract.created_at.desc()).all()


@router.get("/{contract_id}", response_model=ContractOut)
def get_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_contract_or_404(contract_id, current_user.tenant_id, db)


@router.get("/{contract_id}/pdf")
def download_contract_pdf(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = _get_contract_or_404(contract_id, current_user.tenant_id, db)
    pdf_bytes = generate_contract_pdf(contract, db)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=contract-{contract.contract_number}.pdf"
        },
    )


@router.post("/{contract_id}/void", response_model=ContractOut)
def void_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    contract = _get_contract_or_404(contract_id, current_user.tenant_id, db)
    
    if contract.status == ContractStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Contract is already void"
        )
    if contract.status == ContractStatus.signed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Signed contracts cannot be voided"
        )
        
    contract.status = ContractStatus.void
    db.commit()
    db.refresh(contract)
    return contract


@router.post("/bookings/{booking_id}/regenerate", response_model=ContractOut)
def regenerate_contract(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_user.tenant_id,
    ).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Booking not found"
        )

    # Clean up existing contract if present
    existing = db.query(Contract).filter(Contract.booking_id == booking_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    return create_contract_for_booking(booking, db)