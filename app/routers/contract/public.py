# app/routers/contract/public.py
"""
✅ PUBLIC CONTRACT PAGE — view / pdf / sign (client-facing).

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ COPY RULE: client-facing — messages point clients at the agency.
✅ AUDIT (Phase B):
  - Signature base64 validated + size-capped (was: raw 500 / memory abuse).
  - Signature upload failures → typed ServerError.
  - Auto-start swallow now logs instead of silent pass.
  - Sign response carries a success envelope.
"""
import base64
import binascii
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import timeutils
from app.core.errors import (
    AppException,
    BadRequestError,
    GoneError,
    NotFoundError,
    ServerError,
    ValidationFailedError,
    navigate_action,
)
from app.core.limiter import limiter
from app.db.database import get_db, set_public_rls_context, set_rls_context
from app.models.bookings import Booking
from app.models.contracts import Contract, ContractStatus
from app.models.tenant_profile import TenantProfile
from app.schemas.contract import ContractSignPayload, PublicContractView
from app.services.booking_lifecycle import BookingLifecycleService
from app.services.cache import (
    invalidate_booking_cache, invalidate_vehicle_cache, invalidate_contract_cache,
)
from app.services.contract_pdf import generate_contract_pdf
from app.services.storage import upload_file

router = APIRouter()

# ✅ Client-facing errors lead home, never to the dashboard
_PUBLIC_HOME = navigate_action("Go Home", "/")

# ✅ Signature safety: ~1MB decoded is generous for a signature PNG
MAX_SIGNATURE_BYTES = 1_000_000


async def _load_contract_by_token(db, token: str) -> Contract:
    """✅ DRY public token guard: 404 unknown / 410 expired (was triplicated)."""
    await set_public_rls_context(db, token)
    contract = (await db.execute(
        select(Contract).where(Contract.share_token == token)
    )).scalars().first()
    if not contract:
        raise NotFoundError(
            title="Link Not Recognized",
            message="We couldn't find this contract. Check that the link is complete and try again.",
            action=_PUBLIC_HOME,
        )
    if contract.share_token_expires_at and contract.share_token_expires_at < datetime.now(timezone.utc):
        raise GoneError(
            title="Link Expired",
            message="This contract link has expired. Ask the agency to send you a new one.",
            action=_PUBLIC_HOME,
        )
    await set_rls_context(db, tenant_id=contract.tenant_id)
    return contract


async def _load_booking_locked(db, booking_id: int) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
    booking = (await db.execute(stmt)).scalars().first()
    if not booking:
        raise NotFoundError(
            title="Booking Not Found",
            message="We couldn't find this booking. Contact the agency for help.",
            action=_PUBLIC_HOME,
        )
    return booking


def _decode_signature(payload: ContractSignPayload) -> bytes:
    """✅ Phase B: validate + cap client-supplied signature data (was raw 500)."""
    data_url = payload.signature
    if "," in data_url:
        header, _, b64 = data_url.partition(",")
        if not header.startswith("data:image/"):
            raise ValidationFailedError(
                title="Invalid Signature",
                message="The signature must be an image. Please sign again.",
                field_errors={"signature": "Must be an image (PNG/JPG)"},
            )
    else:
        b64 = data_url
    try:
        signature_bytes = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationFailedError(
            title="Invalid Signature",
            message="The signature image couldn't be read. Please sign again.",
            field_errors={"signature": "Couldn't be decoded — sign again"},
        )
    if not signature_bytes or len(signature_bytes) > MAX_SIGNATURE_BYTES:
        raise ValidationFailedError(
            title="Signature Too Large",
            message="The signature image is too large. Please sign again with a simpler stroke.",
            field_errors={"signature": "Keep it under 1 MB"},
        )
    return signature_bytes


@router.get("/public/{token}", response_model=PublicContractView)
@limiter.limit("30/minute")
async def view_contract_public(request: Request, token: str, db=Depends(get_db)):
    contract = await _load_contract_by_token(db, token)

    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client),
        selectinload(Contract.booking).selectinload(Booking.vehicle),
        selectinload(Contract.booking).selectinload(Booking.driver),
        selectinload(Contract.booking).selectinload(Booking.tenant)
    ).where(Contract.share_token == token)

    contract = (await db.execute(stmt)).scalars().unique().first()

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
    contract = await _load_contract_by_token(db, token)

    # ✅ Phase B: PDF engine failures → typed, retryable error (was raw 500)
    try:
        pdf_bytes = await generate_contract_pdf(contract, db)
    except (AppException,):
        raise
    except Exception as e:
        print(f"⚠️ Public contract PDF failed for {contract.id}: {e}")
        raise ServerError(
            title="PDF Not Available Yet",
            message="We couldn't generate the contract PDF just now. Please try again in a moment.",
        )

    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=contract-{contract.contract_number}.pdf"},
    )


@router.post("/public/{token}/sign", response_model=dict)
@limiter.limit("10/minute")
async def sign_contract_public(
    request: Request, token: str, payload: ContractSignPayload, db=Depends(get_db),
):
    contract = await _load_contract_by_token(db, token)

    if contract.status == ContractStatus.void:
        raise BadRequestError(
            title="Contract Voided",
            message="This contract was cancelled by the agency. Contact them for help.",
            action=_PUBLIC_HOME,
        )
    if contract.signed_by_client:
        raise BadRequestError(
            title="Already Signed",
            message="This contract has already been signed. You can view or download it on this page.",
        )

    now = datetime.now(timezone.utc)
    booking = await _load_booking_locked(db, contract.booking_id)

    # ✅ SIGNING IS ALWAYS AVAILABLE — no time gate.
    # Clients can sign immediately to lock in the booking.
    # Auto-start is handled separately below (now/past) or by the scheduler (future).

    # ✅ Signature upload (Cloudinary via storage service) — validated + capped
    signature_bytes = _decode_signature(payload)
    signature_file = UploadFile(
        filename=f"sig_{contract.id}_{int(now.timestamp())}.png",
        file=io.BytesIO(signature_bytes),
        headers={"content-type": "image/png"},
    )
    try:
        signature_url = await upload_file(file=signature_file, tenant_id=contract.tenant_id, category="compliance")
    except (AppException,):
        raise
    except Exception as e:
        print(f"⚠️ Signature upload failed for contract {contract.id}: {e}")
        raise ServerError(
            title="Signature Upload Failed",
            message="We couldn't save your signature. Please try signing again in a moment.",
        )
    contract.signature_image_path = signature_url

    contract.signed_by_client = True
    contract.client_signed_at = now
    contract.status = ContractStatus.signed
    contract.pdf_path = None   # force fresh render with signature
    await db.flush()

    # ✅ AUTO-START: only when pickup time has arrived (now or past).
    # Future pickups stay pending/confirmed — the scheduler starts them at pickup time.
    raw_pickup = booking.pickup_at or booking.start_date
    if raw_pickup is not None:
        pickup_at = timeutils.normalize(raw_pickup)
        if pickup_at <= now:
            try:
                await BookingLifecycleService.start_trip_auto(db, booking)
            except Exception as e:
                # ✅ Phase B: log instead of silent pass — signing still succeeds
                print(f"⚠️ Auto-start skipped for booking {booking.id}: {e}")

    await db.commit()
    await set_rls_context(db, tenant_id=contract.tenant_id)
    await db.refresh(contract)

    # ✅ Invalidate caches so the dashboard flips instantly (no 300s delay)
    await invalidate_booking_cache(booking.tenant_id)
    await invalidate_vehicle_cache(booking.tenant_id)
    await invalidate_contract_cache(booking.tenant_id)

    return {
        "type": "success",
        "title": "Contract Signed",
        "message": "Thank you — your rental agreement is confirmed. The agency has been notified.",
        "contract_number": contract.contract_number,
        "signed_at": now.isoformat(),
    }
