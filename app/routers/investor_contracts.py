import os
import uuid
import base64
from datetime import datetime, timedelta
from typing import Optional
import calendar
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

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
# ✅ NEW: Import cache functions
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
    """
    Generate a new lease contract for an investor vehicle.
    Supports HYBRID flow:
    - If booking_id is provided: Creates a daily contract tied to that specific rental.
    - If duration_months is provided: Creates a fixed-term monthly contract.
    """
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
        # ✅ DAILY FLOW: Fetch booking dates
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
        # ✅ MONTHLY FLOW: Use duration
        duration_months = payload.duration_months
        start_date = datetime.now()
        end_date = add_months(start_date, duration_months)

    # 3. Generate Contract Number (ILC{YYYY}{MM}{###})
    now = datetime.now()
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
        booking_id=payload.booking_id, # Links to booking if daily, null if monthly
        contract_number=contract_number,
        lease_rate=vehicle.investor_lease_rate,
        lease_rate_type=lease_rate_type,
        duration_months=duration_months,
        start_date=start_date,
        end_date=end_date,
        status=InvestorContractStatus.draft,
        share_token=str(uuid.uuid4()),
        share_token_expires_at=now + timedelta(days=14) # Link valid for 14 days
    )
    
    db.add(new_contract)
    await db.commit()
    
    # ✅ Invalidate cache so the new contract appears immediately in lists
    await invalidate_investor_contract_cache(current_user.tenant_id)
    
    await db.refresh(new_contract)
    return new_contract


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
    
    # 1. Try cache first
    status_str = contract_status.value if contract_status else None
    cached = await get_cached_investor_contract_list(
        current_user.tenant_id, 
        vehicle_id=vehicle_id, 
        contract_status=status_str
    )
    if cached is not None:
        return cached

    # 2. Cache miss, fetch from DB
    stmt = select(InvestorContract).where(
        InvestorContract.tenant_id == current_user.tenant_id
    )
    
    if vehicle_id is not None:
        stmt = stmt.where(InvestorContract.vehicle_id == vehicle_id)
    if contract_status is not None:
        stmt = stmt.where(InvestorContract.status == contract_status)
        
    stmt = stmt.order_by(InvestorContract.created_at.desc())
    result = await db.execute(stmt)
    contracts = result.scalars().all()
    
    # 3. Set cache for future requests
    await set_cached_investor_contract_list(
        current_user.tenant_id,
        vehicle_id=vehicle_id,
        contract_status=status_str,
        contracts=contracts
    )
    
    return contracts


@router.post("/{contract_id}/sign")
@limiter.limit("20/minute")
async def sign_investor_contract(
    request: Request,
    contract_id: int,
    payload: InvestorContractSignPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Sign the contract. 
    signer_role must be 'agency' (for the tenant admin) or 'investor'.
    """
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

    now = datetime.now()
    
    # ✅ NEW: Decode and save the signature to disk
    signature_data = payload.signature
    if signature_data.startswith("data:"):
        signature_data = signature_data.split(",", 1)[1]
    
    decoded_bytes = base64.b64decode(signature_data)
    ext = "png" # Frontend uses toDataURL("image/png")
    
    upload_dir = Path("uploads/signatures")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"sig_{contract_id}_{payload.signer_role}_{uuid.uuid4().hex}.{ext}"
    file_path = upload_dir / filename
    
    with open(file_path, "wb") as f:
        f.write(decoded_bytes)

    # ✅ Apply signature and status updates
    if payload.signer_role == 'agency':
        if current_user.role != UserRole.tenant_admin:
            raise HTTPException(status_code=403, detail="Only Tenant Admins can sign for the agency")
        contract.signed_by_agency = True
        contract.agency_signed_at = now
        contract.agency_signature_path = str(file_path) # ✅ SAVE PATH
        
    elif payload.signer_role == 'investor':
        contract.signed_by_investor = True
        contract.investor_signed_at = now
        contract.investor_signature_path = str(file_path) # ✅ SAVE PATH
    else:
        raise HTTPException(status_code=400, detail="Invalid signer role")

    # Check if fully signed
    if contract.signed_by_agency and contract.signed_by_investor:
        contract.status = InvestorContractStatus.signed

    await db.commit()
    
    # ✅ Invalidate cache so the updated signature status appears immediately
    await invalidate_investor_contract_cache(current_user.tenant_id)
    
    await db.refresh(contract)
    return contract


@router.get("/public/{token}")
@limiter.limit("60/minute")
async def public_view_investor_contract(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint for investors to view contract details via email link.
    No authentication required, just the valid share_token.
    """
    stmt = select(InvestorContract).where(InvestorContract.share_token == token)
    result = await db.execute(stmt)
    contract = result.scalars().first()
    
    if not contract:
        raise HTTPException(status_code=404, detail="Invalid contract link")
        
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now():
        raise HTTPException(status_code=410, detail="Contract link has expired")
        
    # Fetch vehicle details for the view
    stmt = select(Vehicle).where(Vehicle.id == contract.vehicle_id)
    result = await db.execute(stmt)
    vehicle = result.scalars().first()
    
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Fetch Investor (Owner) details
    investor_name = "Unknown Investor"
    if vehicle.owner_id:
        user_stmt = select(User).where(User.id == vehicle.owner_id)
        user_res = await db.execute(user_stmt)
        investor = user_res.scalars().first()
        if investor: investor_name = investor.full_name

    # Fetch Booking details if it's a daily contract
    booking_info = None
    if contract.booking_id:
        booking_stmt = select(Booking).where(Booking.id == contract.booking_id)
        booking_res = await db.execute(booking_stmt)
        booking = booking_res.scalars().first()
        if booking:
            booking_info = {
                "booking_number": booking.booking_number,
                "client_name": booking.client_name if hasattr(booking, 'client_name') else "Client"
            }

    return {
        "contract_number": contract.contract_number,
        "investor_name": investor_name,
        "vehicle_details": f"{vehicle.year} {vehicle.make} {vehicle.model} ({vehicle.plate_number})",
        "lease_rate": float(contract.lease_rate),
        "lease_rate_type": contract.lease_rate_type,
        "duration_months": contract.duration_months,
        "start_date": contract.start_date.isoformat(),
        "end_date": contract.end_date.isoformat(),
        "booking_info": booking_info,
        "status": contract.status.value,
        "signed_by_agency": contract.signed_by_agency,
        "signed_by_investor": contract.signed_by_investor,
    }
