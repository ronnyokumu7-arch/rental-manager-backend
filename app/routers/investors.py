import secrets
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db, set_rls_context
from app.core.limiter import limiter
from app.core.config import get_settings
from app.dependencies.auth import get_current_user
from app.models.users import User, UserRole
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.user import UserOut, UserUpdate
from app.schemas.vehicle import VehicleOut, InvestorVehicleCreate, InvestorVehicleAgencyUpdate
from app.services.email import send_investor_invite_email
from app.services.cache import invalidate_user_cache, invalidate_vehicle_cache

router = APIRouter(prefix="/investors", tags=["Investors"])

settings = get_settings()

# ---------------------------------------------------------------------------
# SCHEMAS (Local to this router)
# ---------------------------------------------------------------------------

class InvestorInviteCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = None


# ---------------------------------------------------------------------------
# 1. INVESTOR MANAGEMENT (Invite, List, Update, Delete)
# ---------------------------------------------------------------------------

@router.post("/invite", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def invite_investor(
    request: Request,
    payload: InvestorInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await set_rls_context(db, user_id=current_user.id, tenant_id=current_user.tenant_id, is_super_admin=current_user.role == UserRole.super_admin)

    if current_user.role == UserRole.super_admin:
        raise HTTPException(status_code=400, detail="Super admins cannot generate tenant invite links.")
    if current_user.role != UserRole.tenant_admin:
        raise HTTPException(status_code=403, detail="Only Tenant Admins can invite investors.")

    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Inviting user does not belong to a tenant.")

    stmt = select(User).where(User.email == payload.email.lower())
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(status_code=400, detail="User with this email already exists.")

    invite_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)

    new_investor = User(
        full_name=payload.full_name,
        email=payload.email.lower(),
        phone_number=payload.phone_number,
        role=UserRole.investor,
        tenant_id=tenant_id,
        password_hash=None,
        invite_token=invite_token,
        invite_expires_at=expires_at,
        is_onboarded=False,
        email_verified=False,
    )
    db.add(new_investor)
    
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create invite")
        
    await db.refresh(new_investor)

    agency_name = "Rental Garage"
    tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    if tenant: agency_name = tenant.name

    invite_link = f"{settings.frontend_url}/accept-invite?token={invite_token}"
    
    try:
        await send_investor_invite_email(
            to=payload.email, full_name=payload.full_name,
            invite_link=invite_link, agency_name=agency_name,
            expires_at=expires_at.strftime("%B %d, %Y")
        )
    except Exception as e:
        print(f"️ Email failed: {e}")

    if tenant_id: await invalidate_user_cache(tenant_id)

    return {"message": "Invite created.", "invite_token": invite_token, "invite_link": invite_link}


@router.get("/", response_model=List[UserOut])
@limiter.limit("60/minute")
async def list_investors(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await set_rls_context(db, user_id=current_user.id, tenant_id=current_user.tenant_id, is_super_admin=current_user.role == UserRole.super_admin)

    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    stmt = select(User).where(User.tenant_id == current_user.tenant_id, User.role == UserRole.investor).order_by(desc(User.created_at))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/{investor_id}", response_model=UserOut)
@limiter.limit("30/minute")
async def update_investor(
    request: Request, investor_id: int, updates: UserUpdate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    await set_rls_context(db, user_id=current_user.id, tenant_id=current_user.tenant_id, is_super_admin=current_user.role == UserRole.super_admin)

    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    stmt = select(User).where(User.id == investor_id)
    investor = (await db.execute(stmt)).scalars().first()
    if not investor: raise HTTPException(404, "Investor not found")
    if investor.tenant_id != current_user.tenant_id: raise HTTPException(403, "Access denied: Tenant mismatch")
    if investor.role != UserRole.investor: raise HTTPException(400, "Target is not an investor")

    update_data = updates.model_dump(exclude_unset=True)
    for field in ["role", "tenant_id", "permissions", "is_suspended", "is_active"]:
        update_data.pop(field, None)

    for field, value in update_data.items(): setattr(investor, field, value)

    await db.commit()
    await db.refresh(investor)
    if investor.tenant_id: await invalidate_user_cache(investor.tenant_id)
    return investor


@router.delete("/{investor_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_investor(
    request: Request, investor_id: int,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    await set_rls_context(db, user_id=current_user.id, tenant_id=current_user.tenant_id, is_super_admin=current_user.role == UserRole.super_admin)

    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    stmt = select(User).where(User.id == investor_id)
    investor = (await db.execute(stmt)).scalars().first()
    if not investor: raise HTTPException(404, "Investor not found")
    if investor.tenant_id != current_user.tenant_id: raise HTTPException(403, "Access denied: Tenant mismatch")
    if investor.role != UserRole.investor: raise HTTPException(400, "Target is not an investor")

    vehicle_stmt = select(Vehicle).where(Vehicle.owner_id == investor.id)
    if (await db.execute(vehicle_stmt)).scalars().first():
        raise HTTPException(400, "Cannot delete investor with associated vehicles.")

    await db.delete(investor)
    await db.commit()
    if investor.tenant_id: await invalidate_user_cache(investor.tenant_id)
    return None


# ---------------------------------------------------------------------------
# 2. INVESTOR VEHICLE ONBOARDING BRIDGE
# ---------------------------------------------------------------------------

@router.post("/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_investor_vehicle(
    request: Request,
    payload: InvestorVehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    INVESTOR VEHICLE ONBOARDING BRIDGE.
    Investors submit physical car details. Pricing is restricted.
    """
    if current_user.role != UserRole.investor:
        raise HTTPException(status_code=403, detail="Only investors can use this endpoint.")
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Investor is not linked to an agency.")

    await set_rls_context(db, user_id=current_user.id, tenant_id=current_user.tenant_id, is_super_admin=False)

    # Prevent Duplicate Plates in the same agency
    plate_stmt = select(Vehicle).where(
        Vehicle.tenant_id == current_user.tenant_id,
        Vehicle.plate_number == payload.plate_number.upper()
    )
    if (await db.execute(plate_stmt)).scalars().first():
        raise HTTPException(status_code=400, detail="A vehicle with this plate number already exists in this agency.")

    # ✅ STAMP THE ASSET
    new_vehicle = Vehicle(
        make=payload.make,
        model=payload.model,
        plate_number=payload.plate_number.upper(),
        year=payload.year,
        vin=payload.vin.upper() if payload.vin else None,
        daily_rate=Decimal('0.00'), # ✅ Default to 0 until Agency sets the client rate
        current_mileage=payload.current_mileage,
        next_service_km=payload.next_service_km,
        insurance_number=payload.insurance_number,
        insurance_expiry=payload.insurance_expiry,
        notes=payload.notes,
        status=VehicleStatus.pending_activation, # ✅ RULE: Investors cannot activate
        tenant_id=current_user.tenant_id,        # ✅ RULE: Stamped to agency
        owner_id=current_user.id,                # ✅ RULE: Stamped to investor
        is_archived=False,
    )
    
    db.add(new_vehicle)
    await db.commit()
    await db.refresh(new_vehicle)
    await invalidate_vehicle_cache(new_vehicle.tenant_id)

    return new_vehicle


# ---------------------------------------------------------------------------
# 3. AGENCY HANDOFF: ACTIVATE & PRICE INVESTOR VEHICLE
# ---------------------------------------------------------------------------

@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
@limiter.limit("30/minute")
async def update_investor_vehicle(
    request: Request,
    vehicle_id: int,
    updates: InvestorVehicleAgencyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    AGENCY HANDOFF: Allows Tenant Admins to set the final client rate, 
    update operational metrics, and activate an investor's pending vehicle.
    """
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Access denied.")

    await set_rls_context(db, user_id=current_user.id, tenant_id=current_user.tenant_id, is_super_admin=current_user.role == UserRole.super_admin)

    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    vehicle = (await db.execute(stmt)).scalars().first()
    if not vehicle: raise HTTPException(404, "Vehicle not found")

    # ✅ SECURITY: Ensure this is actually an investor-owned vehicle in this tenant
    if vehicle.owner_id is None:
        raise HTTPException(400, detail="This endpoint is only for investor-owned vehicles. Use standard fleet update for agency cars.")
    if vehicle.tenant_id != current_user.tenant_id:
        raise HTTPException(403, detail="Access denied: Tenant mismatch")

    # Apply restricted updates
    update_data = updates.model_dump(exclude_unset=True)
    
    # ✅ CRITICAL FIX: Force lock the lease rate if a new rate is provided
    if 'investor_lease_rate' in update_data and update_data['investor_lease_rate'] is not None:
        update_data['lease_rate_locked'] = True
        
    for field, value in update_data.items():
        setattr(vehicle, field, value)

    # ✅ Auto-activate if daily_rate is set and status is still pending
    if 'daily_rate' in update_data and vehicle.status == VehicleStatus.pending_activation:
        vehicle.status = VehicleStatus.available

    await db.commit()
    await db.refresh(vehicle)
    await invalidate_vehicle_cache(vehicle.tenant_id)

    return vehicle


# ---------------------------------------------------------------------------
# 4. INVESTOR VEHICLE DOCUMENT UPLOADS
# ---------------------------------------------------------------------------

@router.post("/vehicles/{vehicle_id}/upload-{doc_type}")
async def upload_investor_vehicle_document(
    vehicle_id: int,
    doc_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Allows an investor to upload compliance documents for their own vehicles.
    """
    # 1. Enforce Role
    if current_user.role != UserRole.investor:
        raise HTTPException(status_code=403, detail="Only investors can upload documents here.")
    
    # 2. Validate doc_type (allow 'service_tag' which maps to registration_doc)
    valid_docs = ["insurance", "registration", "inspection", "service_tag"]
    if doc_type not in valid_docs:
        raise HTTPException(status_code=400, detail=f"Invalid document type. Must be one of: {', '.join(valid_docs)}")
        
    # 3. Set RLS and verify ownership
    await set_rls_context(
        db, 
        user_id=current_user.id, 
        tenant_id=current_user.tenant_id, 
        is_super_admin=False
    )
    
    stmt = select(Vehicle).where(
        Vehicle.id == vehicle_id, 
        Vehicle.owner_id == current_user.id
    )
    vehicle = (await db.execute(stmt)).scalars().first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found or you do not own it.")
        
    # 4. Handle file upload (Local filesystem for now; replace with S3/MinIO logic if applicable)
    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    filename = f"{vehicle_id}_{doc_type}_{uuid.uuid4().hex}.{ext}"
    
    upload_dir = "uploads/vehicles"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
        
    # 5. Update database with the new document URL
    # Map 'service_tag' to the existing 'registration_doc' column to avoid DB migration
    db_column_name = "registration_doc" if doc_type == "service_tag" else f"{doc_type}_doc"
    
    file_url = f"/uploads/vehicles/{filename}" 
    
    setattr(vehicle, db_column_name, file_url)
    
    await db.commit()
    await db.refresh(vehicle)
    await invalidate_vehicle_cache(vehicle.tenant_id)
    
    return {
        "message": f"{doc_type.capitalize()} document uploaded successfully",
        "url": file_url
    }
