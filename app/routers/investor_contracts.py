import os
import uuid
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional
import calendar
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse  # ✅ ADDED for PDF serving
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.investor_contracts import InvestorContract, InvestorContractStatus
from app.models.vehicles import Vehicle
from app.models.bookings import Booking
from app.models.users import User, UserRole
from app.schemas.investor_contract import (
    InvestorContractOut, 
    InvestorContractCreate, 
    InvestorContractSignPayload
)
from app.services.cache import (
    get_cached_investor_contract_list,
    set_cached_investor_contract_list,
    invalidate_investor_contract_cache
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


@router.post("/", response_model=InvestorContractOut, status_code=status.HTTP_201_CREATED)
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
        raise HTTPException(status_code=404, detail="Vehicle not found or access denied")
    if vehicle.owner_id is None:
        raise HTTPException(status_code=400, detail="Vehicle is not an investor vehicle")
    if not vehicle.investor_lease_rate:
        raise HTTPException(status_code=400, detail="Vehicle must have a lease rate set before generating a contract")

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
            raise HTTPException(status_code=404, detail="Booking not found for this vehicle")
            
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
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status == InvestorContractStatus.signed:
        raise HTTPException(status_code=400, detail="Contract is already fully signed")

    now = datetime.now(timezone.utc)
    
    signature_data = payload.signature
    if signature_data.startswith("data:"):
        signature_data = signature_data.split(",", 1)[1]
    
    decoded_bytes = base64.b64decode(signature_data)
    ext = "png"
    
    upload_dir = Path("uploads/signatures")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"sig_{contract_id}_{payload.signer_role}_{uuid.uuid4().hex}.{ext}"
    file_path = upload_dir / filename
    
    with open(file_path, "wb") as f:
        f.write(decoded_bytes)

    if payload.signer_role == 'agency':
        if current_user.role != UserRole.tenant_admin:
            raise HTTPException(status_code=403, detail="Only Tenant Admins can sign for the agency")
        contract.signed_by_agency = True
        contract.agency_signed_at = now
        contract.agency_signature_path = str(file_path)
        
    elif payload.signer_role == 'investor':
        contract.signed_by_investor = True
        contract.investor_signed_at = now
        contract.investor_signature_path = str(file_path)
    else:
        raise HTTPException(status_code=400, detail="Invalid signer role")

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
        raise HTTPException(status_code=404, detail="Invalid contract link")
        
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Contract link has expired")
        
    stmt = select(Vehicle).where(Vehicle.id == contract.vehicle_id)
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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


# ✅ NEW: Public Sign Endpoint (For the shareable link flow)
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
        raise HTTPException(status_code=400, detail="Only investors can sign via public link")

    stmt = select(InvestorContract).where(InvestorContract.share_token == token)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Invalid contract link")
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Contract link has expired")
    if contract.status == InvestorContractStatus.signed:
        raise HTTPException(status_code=400, detail="Contract is already fully signed")

    now = datetime.now(timezone.utc)
    signature_data = payload.signature.split(",", 1)[1] if payload.signature.startswith("data:") else payload.signature
    
    decoded_bytes = base64.b64decode(signature_data)
    upload_dir = Path("uploads/signatures")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / f"sig_{contract.id}_investor_{uuid.uuid4().hex}.png"
    with open(file_path, "wb") as f:
        f.write(decoded_bytes)

    contract.signed_by_investor = True
    contract.investor_signed_at = now
    contract.investor_signature_path = str(file_path)

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


# ✅ NEW: PDF Download Endpoint
@router.get("/{contract_id}/pdf")
@limiter.limit("60/minute")
async def get_investor_contract_pdf(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve the generated PDF contract. Accessible via direct link."""
    stmt = select(InvestorContract).where(InvestorContract.id == contract_id)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract or not contract.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found or not yet generated")
    
    file_location = Path(contract.pdf_path)
    if not file_location.exists():
        raise HTTPException(status_code=404, detail="PDF file missing on server")
        
    return FileResponse(
        path=file_location,
        media_type="application/pdf",
        filename=f"Contract_{contract.contract_number}.pdf"
    )
