import base64
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.contracts import Contract, ContractStatus
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle
from app.schemas.contract import ContractSignPayload, PublicContractView
from app.services.contract_pdf import generate_contract_pdf

router = APIRouter()


@router.get("/public/{token}", response_model=PublicContractView)
@limiter.limit("30/minute")
async def view_contract_public(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    # ✅ Optimized: Fetch all related data in a single query
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client),
        selectinload(Contract.booking).selectinload(Booking.vehicle),
        selectinload(Contract.booking).selectinload(Booking.tenant)
    ).where(Contract.share_token == token)
    
    result = await db.execute(stmt)
    contract = result.scalars().unique().first()
    
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This contract link has expired.")

    booking = contract.booking
    
    return PublicContractView(
        contract_number=contract.contract_number,
        booking_id=booking.id,
        tenant_name=booking.tenant.name if booking.tenant else "Unknown",
        client_name=booking.client.full_name if booking.client else "Unknown",
        vehicle_make=booking.vehicle.make if booking.vehicle else "Unknown",
        vehicle_model=booking.vehicle.model if booking.vehicle else "Unknown",
        vehicle_plate=booking.vehicle.plate_number if booking.vehicle else "Unknown",
        start_date=str(booking.start_date),
        end_date=str(booking.end_date),
        total_amount=str(booking.total_amount),
        currency_code=booking.currency_code,
        status=contract.status,
        signed_by_client=contract.signed_by_client,
        created_at=contract.created_at,
    )


@router.get("/public/{token}/pdf")
@limiter.limit("15/minute")
async def download_contract_pdf_public(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Contract).where(Contract.share_token == token)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This contract link has expired.")

    pdf_bytes = await generate_contract_pdf(contract, db)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=contract-{contract.contract_number}.pdf"}
    )


@router.post("/public/{token}/sign", response_model=dict)
@limiter.limit("10/minute")
async def sign_contract_public(
    request: Request,
    token: str,
    payload: ContractSignPayload,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Contract).where(Contract.share_token == token)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This contract link has expired.")

    if contract.status == ContractStatus.void:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This contract has been voided")

    if contract.signed_by_client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contract already signed")

    now = datetime.now(timezone.utc)
    
    # ✅ Process Signature safely (Schema already validated base64, but we extract cleanly)
    signature_data = payload.signature.split(",")[1] if "," in payload.signature else payload.signature
    image_bytes = base64.b64decode(signature_data)
    
    signature_dir = "storage/signatures"
    os.makedirs(signature_dir, exist_ok=True)
    
    filename = f"sig_{contract.id}_{int(now.timestamp())}.png"
    filepath = os.path.join(signature_dir, filename)
    
    with open(filepath, "wb") as f:
        f.write(image_bytes)
        
        contract.signature_image_path = filepath
    contract.signed_by_client = True
    contract.client_signed_at = now
    contract.status = ContractStatus.signed

    # ✅ FIXED: Invalidate the stored (pre-signature) PDF.
    # The tenant download endpoint serves contract.pdf_path when it exists,
    # and that file was rendered BEFORE the client signed. Clearing it forces
    # a fresh render (with the signature) on the next download.
    contract.pdf_path = None

    await db.commit()
    await db.refresh(contract)

    return {
        "message": "Contract signed successfully",
        "contract_number": contract.contract_number,
        "signed_at": now.isoformat()
    }
