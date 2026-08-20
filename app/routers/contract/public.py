import base64
import io
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.models.bookings import Booking
from app.models.clients import Client
   from app.models.tenant_profile import TenantProfile
from app.models.contracts import Contract, ContractStatus
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle
from app.schemas.contract import ContractSignPayload, PublicContractView
from app.services.contract_pdf import generate_contract_pdf
from app.services.storage import upload_file

router = APIRouter()


@router.get("/public/{token}", response_model=PublicContractView)
@limiter.limit("30/minute")
async def view_contract_public(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    # Add TenantProfile to imports at the top of the file:
    # from app.models.tenant_profile import TenantProfile
    
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

    # ✅ NEW: Fetch the OWNING tenant's profile (branding for the public page).
    # This resolves from the contract itself — NOT from any logged-in session.
    # This is what fixes the "ROYRIDE showing on Nairobi Car Hire contracts" bug.
    tenant_profile = None
    if booking.tenant_id:
        profile_stmt = select(TenantProfile).where(TenantProfile.tenant_id == booking.tenant_id)
        tenant_profile = (await db.execute(profile_stmt)).scalars().first()
    
    return PublicContractView(
        contract_number=contract.contract_number,
        booking_id=booking.id,
        tenant_name=booking.tenant.name if booking.tenant else "Unknown",
        # ✅ NEW: Owning agency branding (auto-resolved from contract's tenant)
        tenant_logo_url=tenant_profile.logo_url if tenant_profile else None,
        tenant_address=tenant_profile.address if tenant_profile else None,
        tenant_phone=tenant_profile.phone if tenant_profile else None,
        tenant_email=tenant_profile.email if tenant_profile else None,
        client_name=booking.client.full_name if booking.client else "Unknown",
        id_number=booking.client.id_number if booking.client else None,
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
    
    # ✅ Process Signature safely and upload to Cloudinary via storage service
    signature_b64 = payload.signature.split(",")[1] if "," in payload.signature else payload.signature
    signature_bytes = base64.b64decode(signature_b64)

    signature_file = UploadFile(
        filename=f"sig_{contract.id}_{int(now.timestamp())}.png",
        file=io.BytesIO(signature_bytes),
        headers={"content-type": "image/png"},
    )

    # Store under the "compliance" category (5MB limit, fits signatures perfectly)
    signature_url = await upload_file(
        file=signature_file,
        tenant_id=contract.tenant_id,
        category="compliance",
    )
    contract.signature_image_path = signature_url
    
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
