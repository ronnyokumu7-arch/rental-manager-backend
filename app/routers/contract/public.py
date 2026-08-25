import base64
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.models.bookings import Booking
from app.models.contracts import Contract, ContractStatus
from app.models.tenant_profile import TenantProfile
from app.schemas.contract import ContractSignPayload, PublicContractView
from app.services.booking_lifecycle import BookingLifecycleService
from app.services.contract_pdf import generate_contract_pdf
from app.services.storage import upload_file

router = APIRouter()


async def _load_booking_locked(db, booking_id: int) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
    booking = (await db.execute(stmt)).scalars().first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.get("/public/{token}", response_model=PublicContractView)
@limiter.limit("30/minute")
async def view_contract_public(request: Request, token: str, db=Depends(get_db)):
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client),
        selectinload(Contract.booking).selectinload(Booking.vehicle),
        selectinload(Contract.booking).selectinload(Booking.driver),
        selectinload(Contract.booking).selectinload(Booking.tenant)
    ).where(Contract.share_token == token)

    contract = (await db.execute(stmt)).scalars().unique().first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This contract link has expired.")

    booking = contract.booking
    driver = booking.driver if booking else None

    tenant_profile = None
    if booking.tenant_id:
        tenant_profile = (await db.execute(
            select(TenantProfile).where(TenantProfile.tenant_id == booking.tenant_id)
        )).scalars().first()

    return PublicContractView(
        contract_number=contract.contract_number,
        booking_id=booking.id,
        tenant_name=booking.tenant.name if booking.tenant else "Unknown",
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
        driver_name=driver.full_name if driver else None,
        driver_phone=driver.phone if driver else None,
        driver_dl_number=driver.dl_number if driver else None,
    )


@router.get("/public/{token}/pdf")
@limiter.limit("15/minute")
async def download_contract_pdf_public(request: Request, token: str, db=Depends(get_db)):
    stmt = select(Contract).where(Contract.share_token == token)
    contract = (await db.execute(stmt)).scalars().first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This contract link has expired.")

    pdf_bytes = await generate_contract_pdf(contract, db)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=contract-{contract.contract_number}.pdf"},
    )


@router.post("/public/{token}/sign", response_model=dict)
@limiter.limit("10/minute")
async def sign_contract_public(
    request: Request, token: str, payload: ContractSignPayload, db=Depends(get_db),
):
    stmt = select(Contract).where(Contract.share_token == token)
    contract = (await db.execute(stmt)).scalars().first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This contract link has expired.")
    if contract.status == ContractStatus.void:
        raise HTTPException(status_code=400, detail="This contract has been voided")
    if contract.signed_by_client:
        raise HTTPException(status_code=400, detail="Contract already signed")

    now = datetime.now(timezone.utc)
    booking = await _load_booking_locked(db, contract.booking_id)

    # ✅ GATE: signing is the final handover step — only live at/after pickup.
    pickup = booking.pickup_at or booking.start_date
    pickup_aware = pickup if pickup.tzinfo else pickup.replace(tzinfo=timezone.utc)
    if now < pickup_aware:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Signing opens at the scheduled pickup time.",
        )

    # ✅ Signature upload (Cloudinary via storage service)
    signature_b64 = payload.signature.split(",")[1] if "," in payload.signature else payload.signature
    signature_bytes = base64.b64decode(signature_b64)
    signature_file = UploadFile(
        filename=f"sig_{contract.id}_{int(now.timestamp())}.png",
        file=io.BytesIO(signature_bytes),
        headers={"content-type": "image/png"},
    )
    signature_url = await upload_file(file=signature_file, tenant_id=contract.tenant_id, category="compliance")
    contract.signature_image_path = signature_url

    contract.signed_by_client = True
    contract.client_signed_at = now
    contract.status = ContractStatus.signed
    contract.pdf_path = None   # force fresh render with signature
    await db.flush()

    # ✅ SIGNED ⇒ AUTO-START (handover happened). Manual "Start Trip" = fallback.
    try:
        await BookingLifecycleService.start_trip_auto(db, booking)
    except HTTPException:
        pass  # preconditions not met → operator starts the trip manually

    await db.commit()
    await db.refresh(contract)

    return {
        "message": "Contract signed successfully",
        "contract_number": contract.contract_number,
        "signed_at": now.isoformat(),
    }
