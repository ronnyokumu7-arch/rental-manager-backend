# app/routers/investor_contracts.py
"""
Investor Contracts — generation, signing (auth + public), and PDF serving.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B):
  - Base64 signature decoding is validated to prevent raw 500s on bad input.
  - File I/O is wrapped in try/except to prevent raw 500s on disk/permission errors.
"""
import base64
import binascii
import calendar
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import (
    AuthorizationError,
    BadRequestError,
    GoneError,
    NotFoundError,
    ServerError,
    ValidationFailedError,
)
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking
from app.models.investor_contracts import InvestorContract, InvestorContractStatus
from app.models.users import User, UserRole
from app.models.vehicles import Vehicle
from app.schemas.investor_contract import (
    InvestorContractCreate,
    InvestorContractOut,
    InvestorContractSignPayload,
)
from app.services.cache import (
    get_cached_investor_contract_list,
    invalidate_investor_contract_cache,
    set_cached_investor_contract_list,
)

router = APIRouter(prefix="/investor-contracts", tags=["Investor Contracts"])
settings = get_settings()


# Helper to add months safely (handling month-end dates)
def add_months(sourcedate: datetime, months: int) -> datetime:
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(sourcedate.day, max_day)
    return sourcedate.replace(year=year, month=month, day=day)


def _decode_signature(signature_data: str) -> bytes:
    """✅ Phase B: safely decode base64 signature, preventing raw 500s."""
    if signature_data.startswith("data:"):
        signature_data = signature_data.split(",", 1)[1]
    try:
        return base64.b64decode(signature_data, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationFailedError(
            title="Invalid Signature",
            message="The signature data is corrupted or invalid.",
            field_errors={"signature": "Invalid base64 data"},
        )


def _save_signature(contract_id: int, signer_role: str, signature_bytes: bytes) -> str:
    """✅ Phase B: safely save signature to disk, preventing raw 500s on I/O errors."""
    try:
        upload_dir = Path("uploads/signatures")
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"sig_{contract_id}_{signer_role}_{uuid.uuid4().hex}.png"
        file_path = upload_dir / filename
        with open(file_path, "wb") as f:
            f.write(signature_bytes)
        return str(file_path)
    except OSError as e:
        print(f"⚠️ Signature save failed for contract {contract_id}: {e}")
        raise ServerError(
            title="Signature Save Failed",
            message="We couldn't save your signature. Please try again or contact support.",
        )


@router.post("/", response_model=InvestorContractOut, status_code=201)
@limiter.limit("30/minute")
async def generate_investor_contract(
    request: Request,
    payload: InvestorContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a new lease contract for an investor vehicle."""
    # 1. Verify Vehicle Ownership & Tenant
    stmt = select(Vehicle).where(
        Vehicle.id == payload.vehicle_id, 
        Vehicle.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise NotFoundError(
            title="Vehicle Not Found",
            message="Vehicle not found or access denied.",
        )
    if vehicle.owner_id is None:
        raise BadRequestError(
            title="Invalid Vehicle",
            message="Vehicle is not an investor vehicle.",
        )
    if not vehicle.investor_lease_rate:
        raise BadRequestError(
            title="Missing Lease Rate",
            message="Vehicle must have a lease rate set before generating a contract.",
        )

    # 2. Determine Contract Type & Dates
    start_date = None
    end_date = None
    duration_months = None
    lease_rate_type = vehicle.lease_rate_type or 'monthly'
    
    if payload.booking_id:
        booking_stmt = select(Booking).where(
            Booking.id == payload.booking_id, 
            Booking.vehicle_id == vehicle.id
        )
        booking_res = await db.execute(booking_stmt)
        booking = booking_res.scalars().first()
        
        if not booking:
            raise NotFoundError(
                title="Booking Not Found",
                message="Booking not found for this vehicle.",
            )
            
        start_date = booking.start_date
        end_date = booking.end_date
        lease_rate_type = 'daily'
    else:
        duration_months = payload.duration_months
        start_date = datetime.now(timezone.utc)
        end_date = add_months(start_date, duration_months)

    # 3. Generate Contract Number (ILC{YYYY}{MM}{###})
    now = datetime.now(timezone.utc)
    count_stmt = select(func.count(InvestorContract.id)).where(
        InvestorContract.tenant_id == current_user.tenant_id,
        func.extract('year', InvestorContract.created_at) == now.year,
        func.extract('month', InvestorContract.created_at) == now.month
    )
    count = (await db.execute(count_stmt)).scalar() or 0
    contract_number = f"ILC{now.year}{now.month:02d}{count + 1:03d}"

    # 4. Create Contract
    new_contract = InvestorContract(
        tenant_id=current_user.tenant_id,
        vehicle_id=vehicle.id,
        booking_id=payload.booking_id,
        contract_number=contract_number,
        lease_rate=vehicle.investor_lease_rate,
        lease_rate_type=lease_rate_type,
        duration_months=duration_months,
        start_date=start_date,
        end_date=end_date,
        status=InvestorContractStatus.draft,
        share_token=str(uuid.uuid4()),
        share_token_expires_at=now + timedelta(days=14)
    )
    
    db.add(new_contract)
    await db.commit()
    await invalidate_investor_contract_cache(current_user.tenant_id)
    
    # ✅ PRODUCTION FIX: Re-fetch with eager loading to prevent MissingGreenlet errors 
    stmt = (
        select(InvestorContract)
        .where(InvestorContract.id == new_contract.id)
        .options(
            selectinload(InvestorContract.tenant),
            selectinload(InvestorContract.vehicle).selectinload(Vehicle.owner),
            selectinload(InvestorContract.booking)
        )
    )
    result = await db.execute(stmt)
    final_contract = result.scalars().first()
    
    return final_contract


@router.get("/", response_model=list[InvestorContractOut])
@limiter.limit("60/minute")
async def list_investor_contracts(
    request: Request,
    vehicle_id: Optional[int] = Query(None, description="Filter by specific vehicle"),
    contract_status: Optional[InvestorContractStatus] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all investor contracts for the current tenant (with caching)."""
    status_str = contract_status.value if contract_status else None
    cached = await get_cached_investor_contract_list(
        current_user.tenant_id, 
        vehicle_id=vehicle_id, 
        contract_status=status_str
    )
    if cached is not None:
        return cached

    # ✅ PRODUCTION FIX: Eager load relationships for Pydantic serialization
    stmt = (
        select(InvestorContract)
        .where(InvestorContract.tenant_id == current_user.tenant_id)
        .options(
            selectinload(InvestorContract.tenant),
            selectinload(InvestorContract.vehicle).selectinload(Vehicle.owner),
            selectinload(InvestorContract.booking)
        )
    )
    
    if vehicle_id is not None:
        stmt = stmt.where(InvestorContract.vehicle_id == vehicle_id)
    if contract_status is not None:
        stmt = stmt.where(InvestorContract.status == contract_status)
        
    stmt = stmt.order_by(InvestorContract.created_at.desc())
    result = await db.execute(stmt)
    contracts = result.scalars().all()
    
    await set_cached_investor_contract_list(
        current_user.tenant_id,
        vehicle_id=vehicle_id,
        contract_status=status_str,
        contracts=contracts
    )
    
    return contracts


@router.post("/{contract_id}/sign", response_model=InvestorContractOut)
@limiter.limit("20/minute")
async def sign_investor_contract(
    request: Request,
    contract_id: int,
    payload: InvestorContractSignPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sign the contract (Authenticated flow)."""
    stmt = select(InvestorContract).where(
        InvestorContract.id == contract_id,
        InvestorContract.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise NotFoundError(
            title="Contract Not Found",
            message="Contract not found.",
        )
    if contract.status == InvestorContractStatus.signed:
        raise BadRequestError(
            title="Already Signed",
            message="Contract is already fully signed.",
        )

    now = datetime.now(timezone.utc)
    
    # ✅ Phase B: Safe decode + safe save
    signature_bytes = _decode_signature(payload.signature)
    file_path = _save_signature(contract_id, payload.signer_role, signature_bytes)

    if payload.signer_role == 'agency':
        if current_user.role != UserRole.tenant_admin:
            raise AuthorizationError(
                title="Permission Denied",
                message="Only Tenant Admins can sign for the agency.",
            )
        contract.signed_by_agency = True
        contract.agency_signed_at = now
        contract.agency_signature_path = file_path
        
    elif payload.signer_role == 'investor':
        contract.signed_by_investor = True
        contract.investor_signed_at = now
        contract.investor_signature_path = file_path
    else:
        raise BadRequestError(
            title="Invalid Signer Role",
            message="Invalid signer role.",
        )

    if contract.signed_by_agency and contract.signed_by_investor:
        contract.status = InvestorContractStatus.signed

    await db.commit()
    await invalidate_investor_contract_cache(current_user.tenant_id)
    
    # ✅ PRODUCTION FIX: Re-fetch with eager loading before returning
    stmt = (
        select(InvestorContract)
        .where(InvestorContract.id == contract_id)
        .options(
            selectinload(InvestorContract.tenant),
            selectinload(InvestorContract.vehicle).selectinload(Vehicle.owner),
            selectinload(InvestorContract.booking)
        )
    )
    result = await db.execute(stmt)
    final_contract = result.scalars().first()
    return final_contract


@router.get("/public/{token}")
@limiter.limit("60/minute")
async def public_view_investor_contract(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint for investors to view contract details via email link."""
    stmt = select(InvestorContract).where(InvestorContract.share_token == token)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise NotFoundError(
            title="Invalid Link",
            message="Invalid contract link.",
        )
        
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise GoneError(
            title="Link Expired",
            message="Contract link has expired.",
        )
        
    stmt = select(Vehicle).where(Vehicle.id == contract.vehicle_id)
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise NotFoundError(
            title="Vehicle Not Found",
            message="Vehicle not found.",
        )

    investor_name = "Unknown Investor"
    if vehicle.owner_id:
        user_stmt = select(User).where(User.id == vehicle.owner_id)
        user_res = await db.execute(user_stmt)
        investor = user_res.scalars().first()
        if investor: 
            investor_name = investor.full_name

    booking_info = None
    if contract.booking_id:
        booking_stmt = select(Booking).where(Booking.id == contract.booking_id)
        booking_res = await db.execute(booking_stmt)
        booking = booking_res.scalars().first()
        if booking:
            booking_info = {
                "booking_number": booking.booking_number,
                "client_name": getattr(booking, 'client_name', "Client")
            }

    return {
        "contract_number": contract.contract_number,
        "investor_name": investor_name,
        "vehicle_details": f"{vehicle.year} {vehicle.make} {vehicle.model} ({vehicle.plate_number})",
        "lease_rate": float(contract.lease_rate),
        "lease_rate_type": contract.lease_rate_type,
        "duration_months": contract.duration_months,
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "booking_info": booking_info,
        "status": contract.status.value,
        "signed_by_agency": contract.signed_by_agency,
        "signed_by_investor": contract.signed_by_investor,
    }


@router.post("/public/{token}/sign", response_model=InvestorContractOut)
@limiter.limit("20/minute")
async def public_sign_investor_contract(
    request: Request,
    token: str,
    payload: InvestorContractSignPayload,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint for investors to sign via email link."""
    if payload.signer_role != 'investor':
        raise BadRequestError(
            title="Invalid Signer Role",
            message="Only investors can sign via public link.",
        )

    stmt = select(InvestorContract).where(InvestorContract.share_token == token)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise NotFoundError(
            title="Invalid Link",
            message="Invalid contract link.",
        )
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise GoneError(
            title="Link Expired",
            message="Contract link has expired.",
        )
    if contract.status == InvestorContractStatus.signed:
        raise BadRequestError(
            title="Already Signed",
            message="Contract is already fully signed.",
        )

    now = datetime.now(timezone.utc)
    
    # ✅ Phase B: Safe decode + safe save
    signature_bytes = _decode_signature(payload.signature)
    file_path = _save_signature(contract.id, 'investor', signature_bytes)

    contract.signed_by_investor = True
    contract.investor_signed_at = now
    contract.investor_signature_path = file_path

    if contract.signed_by_agency and contract.signed_by_investor:
        contract.status = InvestorContractStatus.signed

    await db.commit()
    await invalidate_investor_contract_cache(contract.tenant_id)
    
    # Re-fetch with eager loading
    stmt = select(InvestorContract).where(InvestorContract.id == contract.id).options(
        selectinload(InvestorContract.tenant),
        selectinload(InvestorContract.vehicle).selectinload(Vehicle.owner),
        selectinload(InvestorContract.booking)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


@router.get("/{contract_id}/pdf")
@limiter.limit("60/minute")
async def get_investor_contract_pdf(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve the generated PDF contract. Triggers generation if missing."""
    from app.services.investor_contract import render_and_store_investor_contract_pdf
    
    stmt = select(InvestorContract).where(InvestorContract.id == contract_id)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise NotFoundError(
            title="Contract Not Found",
            message="Contract not found.",
        )
    
    # ✅ TRIGGER GENERATION: If PDF path is missing or file doesn't exist on disk, generate it now.
    if not contract.pdf_path or not Path(contract.pdf_path).exists():
        await render_and_store_investor_contract_pdf(contract_id)
        # Re-fetch to get the newly saved path
        result = await db.execute(stmt)
        contract = result.scalars().first()

    if not contract.pdf_path or not Path(contract.pdf_path).exists():
        raise NotFoundError(
            title="PDF Not Found",
            message="PDF file missing on server and generation failed.",
        )
        
    return FileResponse(
        path=contract.pdf_path,
        media_type="application/pdf",
        filename=f"Contract_{contract.contract_number}.pdf"
    )
