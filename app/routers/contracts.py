from datetime import datetime, timedelta, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.contracts import Contract, ContractStatus
from app.models.tenants import Tenant
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.contract import ContractOut, PublicContractView
from app.services.contracts import create_contract_for_booking
from app.services.pdf import generate_contract_pdf
from app.services.email import send_contract_to_client

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

# ─── Generate Shareable Link ──────────────────────────────────────────────
@router.post("/{contract_id}/share-link", response_model=dict)
def generate_share_link(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Generate a secure shareable link for the contract"""
    contract = _get_contract_or_404(contract_id, current_user.tenant_id, db)
    
    if contract.status == ContractStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Void contracts cannot be shared"
        )
    
    # Generate secure token
    share_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    
    contract.share_token = share_token
    contract.share_token_expires_at = expires_at
    contract.status = ContractStatus.sent
    
    db.commit()
    db.refresh(contract)
    
    base_url = "https://rental-manager-frontend.vercel.app"
    share_url = f"{base_url}/contracts/view/{share_token}"
    
    return {
        "share_token": share_token,
        "share_url": share_url,
        "expires_at": expires_at
    }

# ─── Send Contract to Client via Email ────────────────────────────────────
@router.post("/{contract_id}/send-to-client", response_model=ContractOut)
def send_contract_to_client_endpoint(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Generate share link and email it to the client"""
    contract = _get_contract_or_404(contract_id, current_user.tenant_id, db)
    
    booking = db.query(Booking).filter(Booking.id == contract.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    if not client or not client.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client email not available"
        )
    
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    
    # Generate share link if not already generated
    if not contract.share_token:
        share_token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        contract.share_token = share_token
        contract.share_token_expires_at = expires_at
    
    contract.status = ContractStatus.sent
    
    db.commit()
    db.refresh(contract)
    
    base_url = "https://rental-manager-frontend.vercel.app"
    share_url = f"{base_url}/contracts/view/{contract.share_token}"
    
    # Send email
    send_contract_to_client(
        to=client.email,
        client_name=client.full_name,
        contract_number=contract.contract_number,
        vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})",
        start_date=str(booking.start_date),
        end_date=str(booking.end_date),
        total_amount=str(booking.total_amount),
        currency=booking.currency_code,
        contract_url=share_url,
    )
    
    return contract

# ─── PUBLIC: View Contract by Token ───────────────────────────────────────
@router.get("/public/{token}", response_model=PublicContractView)
def view_contract_public(
    token: str,
    db: Session = Depends(get_db),
):
    """Public endpoint to view contract details by share token"""
    contract = db.query(Contract).filter(Contract.share_token == token).first()
    
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract not found"
        )
    
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This contract link has expired. Please request a new one."
        )
    
    booking = db.query(Booking).filter(Booking.id == contract.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    tenant = db.query(Tenant).filter(Tenant.id == booking.tenant_id).first()
    
    return PublicContractView(
        contract_number=contract.contract_number,
        booking_id=booking.id,
        tenant_name=tenant.name if tenant else "Unknown",
        client_name=client.full_name if client else "Unknown",
        vehicle_make=vehicle.make if vehicle else "Unknown",
        vehicle_model=vehicle.model if vehicle else "Unknown",
        vehicle_plate=vehicle.plate_number if vehicle else "Unknown",
        start_date=str(booking.start_date),
        end_date=str(booking.end_date),
        total_amount=str(booking.total_amount),
        currency_code=booking.currency_code,
        status=contract.status,
        signed_by_client=contract.signed_by_client,
        created_at=contract.created_at,
    )

# ─── PUBLIC: Download Contract PDF by Token ───────────────────────────────
@router.get("/public/{token}/pdf")
def download_contract_pdf_public(
    token: str,
    db: Session = Depends(get_db),
):
    """Public endpoint to download contract PDF by share token"""
    contract = db.query(Contract).filter(Contract.share_token == token).first()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This contract link has expired"
        )
    
    pdf_bytes = generate_contract_pdf(contract, db)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=contract-{contract.contract_number}.pdf"
        },
    )

# ─── PUBLIC: Sign Contract by Token ───────────────────────────────────────
@router.post("/public/{token}/sign", response_model=dict)
def sign_contract_public(
    token: str,
    db: Session = Depends(get_db),
):
    """Allow client to sign contract via share token"""
    contract = db.query(Contract).filter(Contract.share_token == token).first()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This contract link has expired"
        )
    
    if contract.status == ContractStatus.void:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This contract has been voided and cannot be signed"
        )
    
    if contract.signed_by_client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contract has already been signed by the client"
        )
    
    now = datetime.now(timezone.utc)
    contract.signed_by_client = True
    contract.client_signed_at = now
    contract.status = ContractStatus.signed
    
    db.commit()
    
    return {
        "message": "Contract signed successfully",
        "contract_number": contract.contract_number,
        "signed_at": now
    }
    
    

# 1. Public View Endpoint (No Auth Required)
@router.get("/public/{share_token}")
async def get_public_contract(share_token: str, db: Session = Depends(get_db)):
    contract = db.query(Contract).filter(Contract.share_token == share_token).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Invalid or expired contract link.")
    
    # Fetch related data to show on the public page
    booking = db.query(Booking).filter(Booking.id == contract.booking_id).first()
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    
    return {
        "contract": contract,
        "booking": booking,
        "client": {"full_name": client.full_name, "dl_number": client.dl_number, "phone": client.phone},
        "vehicle": {"make": vehicle.make, "model": vehicle.model, "plate_number": vehicle.plate_number}
    }

# 2. Public Sign Endpoint (No Auth Required)
@router.post("/public/{share_token}/sign")
async def sign_public_contract(share_token: str, payload: dict, db: Session = Depends(get_db)):
    contract = db.query(Contract).filter(Contract.share_token == share_token).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Invalid contract link.")
    
    if contract.status == "signed":
        raise HTTPException(status_code=400, detail="Contract already signed.")

    # Update status and save the typed name/signature
    contract.status = "signed"
    contract.signed_at = datetime.utcnow()
    # Assuming you have a 'signed_name' or 'signature_data' column. If not, just update status.
    db.commit()
    
    return {"message": "Contract signed successfully", "status": "signed"}
