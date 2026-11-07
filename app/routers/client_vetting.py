"""
✅ VETTING ENGINE — Identity binding for Clients and Drivers.

✅ FLOW:
  1. Admin triggers verification -> generates token, sets status=sent.
  2. Public user opens link -> sees preview.
  3. Public user uploads selfie -> secure ingest (hash + watermark).
  4. Public user submits -> status=under_review.
  5. Admin reviews -> approves (verified + active) or rejects (retryable).

✅ SECURITY:
  - Public endpoints are token-scoped, rate-limited, no JWT required.
  - Admin endpoints require tenant scope.
  - Tokens are single-use and expire (72h default).
"""
import io
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import BadRequestError, ConflictError, GoneError, NotFoundError, ServerError, ValidationFailedError, navigate_action
from app.core.limiter import limiter
from app.db.database import get_db, set_public_rls_context, set_rls_context
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.dependencies.tenant import require_mutation_tenant_scope, TenantScope
from app.models.clients import Client, ClientStatus, ClientVerificationStatus
from app.models.drivers import Driver, DriverVerificationStatus
from app.models.tenants import Tenant
from app.models.users import User
from app.schemas.vetting import (
    StartVerificationOut,
    PublicVettingPreviewOut,
    VettingSubmitPayload,
    VettingReviewPayload,
    VettingDrivingDetails,
    CLIENT_VETTING_STEPS,
    DRIVER_VETTING_STEPS,
)
from app.services.client_verification import missing_client_verification_requirements
from app.services.document_security import secure_prepare, register_document, assert_allowed_content_type
from app.services.storage import upload_file

router = APIRouter()

_PUBLIC_HOME = navigate_action("Go Home", "/")

# ✅ Get frontend URL from environment, default to localhost for dev
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _get_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=72)


async def _get_tenant_name(db: AsyncSession, tenant_id: int) -> str:
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(stmt)).scalars().first()
    return tenant.name if tenant else "Agency"


async def _resolve_vetting_target(
    db: AsyncSession, person_type: Literal["client", "driver"], person_id: int, tenant_id: int
):
    """Fetches Client or Driver, enforcing tenant isolation."""
    if person_type == "client":
        stmt = select(Client).where(Client.id == person_id, Client.tenant_id == tenant_id)
    else:
        stmt = select(Driver).where(Driver.id == person_id, Driver.tenant_id == tenant_id)
    
    target = (await db.execute(stmt)).scalars().first()
    if not target:
        raise NotFoundError(title="Person Not Found", message=f"This {person_type} does not exist in your agency.")
    return target


async def _resolve_token_target(db: AsyncSession, token: str):
    """Resolves a public vetting token to a Client or Driver."""
    await set_public_rls_context(db, token)
    
    # Check Client
    stmt = select(Client).where(
        Client.verification_token == token,
        Client.verification_status.in_([ClientVerificationStatus.sent, ClientVerificationStatus.under_review])
    )
    client = (await db.execute(stmt)).scalars().first()
    if client:
        await set_rls_context(db, tenant_id=client.tenant_id)
        return "client", client
    
    # Check Driver
    stmt = select(Driver).where(
        Driver.verification_token == token,
        Driver.verification_status.in_([DriverVerificationStatus.sent, DriverVerificationStatus.under_review])
    )
    driver = (await db.execute(stmt)).scalars().first()
    if driver:
        await set_rls_context(db, tenant_id=driver.tenant_id)
        return "driver", driver
    
    raise GoneError(
        title="Link Invalid",
        message="This verification link is invalid, expired, or already used.",
        action=_PUBLIC_HOME,
    )


# ─── ADMIN: START VERIFICATION ───────────────────────────────────────────────

@router.post("/clients/{client_id}/start-verification", response_model=StartVerificationOut)
@limiter.limit("10/minute")
async def start_client_verification(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    client = await _resolve_vetting_target(db, "client", client_id, scope.tenant_id)
    
    token = _generate_token()
    client.verification_token = token
    client.verification_expires_at = _get_expiry()
    client.verification_status = ClientVerificationStatus.sent.value
    client.rejection_notes = None  # Clear previous notes
    
    await db.commit()
    await db.refresh(client)
    
    # ✅ FIX: Use the frontend URL, not the backend's request.base_url
    link = f"{FRONTEND_URL}/vetting/{token}"
    
    return StartVerificationOut(
        verification_link=link,
        channels_sent=["manual"],  # Update when email/whatsapp is integrated
        expires_at=client.verification_expires_at,
    )


@router.post("/drivers/{driver_id}/start-verification", response_model=StartVerificationOut)
@limiter.limit("10/minute")
async def start_driver_verification(
    request: Request,
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    driver = await _resolve_vetting_target(db, "driver", driver_id, scope.tenant_id)
    
    token = _generate_token()
    driver.verification_token = token
    driver.verification_expires_at = _get_expiry()
    driver.verification_status = DriverVerificationStatus.sent.value
    driver.rejection_notes = None
    
    await db.commit()
    await db.refresh(driver)
    
    # ✅ FIX: Use the frontend URL, not the backend's request.base_url
    link = f"{FRONTEND_URL}/vetting/{token}"
    
    return StartVerificationOut(
        verification_link=link,
        channels_sent=["manual"],
        expires_at=driver.verification_expires_at,
    )


# ─── PUBLIC: PREVIEW ─────────────────────────────────────────────────────────

@router.get("/vetting/preview/{token}", response_model=PublicVettingPreviewOut)
@limiter.limit("30/minute")
async def preview_vetting(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    person_type, target = await _resolve_token_target(db, token)
    
    # Check expiry
    if target.verification_expires_at and target.verification_expires_at < datetime.now(timezone.utc):
        raise GoneError(title="Link Expired", message="This verification link has expired.", action=_PUBLIC_HOME)
    
    tenant_name = await _get_tenant_name(db, target.tenant_id)
    first_name = target.full_name.split()[0] if target.full_name else "there"
    steps = CLIENT_VETTING_STEPS if person_type == "client" else DRIVER_VETTING_STEPS
    
    return PublicVettingPreviewOut(
        person_type=person_type,
        tenant_name=tenant_name,
        expires_at=target.verification_expires_at,
        person_first_name=first_name,
        steps=steps,
    )


# ─── PUBLIC: VERIFICATION STEP 1 ────────────────────────────────────────────

@router.put("/vetting/{token}/driving-details", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def save_vetting_driving_details(
    request: Request,
    token: str,
    payload: VettingDrivingDetails,
    db: AsyncSession = Depends(get_db),
):
    """Save the conditional driving data after basic account creation."""
    person_type, client = await _resolve_token_target(db, token)
    if person_type != "client":
        raise ValidationFailedError(
            title="Unsupported Verification Step",
            message="Driving details can only be supplied for a client verification.",
        )

    client.driving_arrangement = payload.driving_arrangement
    if payload.driving_arrangement == "self_drive":
        client.dl_number = payload.dl_number.strip().upper() if payload.dl_number else None
        client.dl_expiry = payload.dl_expiry
        client.dl_issued_date = payload.dl_issued_date
        # Evidence must match the newly declared licence.
        client.dl_image_front = None
        for field in (
            "driver_full_name", "driver_phone", "driver_id_number", "driver_dl_number",
            "driver_dl_expiry", "driver_dl_issued_date", "driver_id_image_front", "driver_dl_image_front",
        ):
            setattr(client, field, None)
    elif payload.driving_arrangement == "own_driver":
        client.dl_number = None
        client.dl_expiry = None
        client.dl_issued_date = None
        client.driver_full_name = payload.driver_full_name
        client.driver_phone = payload.driver_phone
        client.driver_id_number = payload.driver_id_number.strip().upper() if payload.driver_id_number else None
        client.driver_dl_number = payload.driver_dl_number.strip().upper() if payload.driver_dl_number else None
        client.driver_dl_expiry = payload.driver_dl_expiry
        client.driver_dl_issued_date = payload.driver_dl_issued_date
        # A driver can be changed between attempts; never retain the previous
        # driver's evidence after details are re-submitted.
        client.driver_id_image_front = None
        client.driver_dl_image_front = None
    else:  # chauffeur
        client.dl_number = None
        client.dl_expiry = None
        client.dl_issued_date = None
        client.dl_image_front = None
        for field in (
            "driver_full_name", "driver_phone", "driver_id_number", "driver_dl_number",
            "driver_dl_expiry", "driver_dl_issued_date", "driver_id_image_front", "driver_dl_image_front",
        ):
            setattr(client, field, None)

    await db.commit()
    return {"type": "success", "message": "Driving details saved."}


@router.post("/vetting/{token}/upload-document", status_code=status.HTTP_201_CREATED)
@limiter.limit("15/minute")
async def upload_vetting_document(
    request: Request,
    token: str,
    slot: Literal["id_front", "id_back", "dl_front", "driver_id_front", "driver_dl_front"] = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Token-scoped document upload for verification step 1.

    The client chooses camera or device in the UI; both reach this same secure
    endpoint. Selfies deliberately use the separate camera-only endpoint.
    """
    person_type, target = await _resolve_token_target(db, token)
    if person_type != "client":
        raise ValidationFailedError(title="Unsupported Verification Step", message="Use the driver verification flow for driver documents.")

    arrangement = target.driving_arrangement
    if slot == "dl_front" and arrangement != "self_drive":
        raise ValidationFailedError(title="Document Not Needed", message="A client licence is only needed for self-drive.")
    if slot in {"driver_id_front", "driver_dl_front"} and arrangement != "own_driver":
        raise ValidationFailedError(title="Document Not Needed", message="Personal-driver documents are only needed for My Driver.")

    assert_allowed_content_type(file.content_type, allow_pdf=False)
    raw_bytes = await file.read()
    tenant_name = await _get_tenant_name(db, target.tenant_id)
    stamped_bytes, file_hash = await secure_prepare(
        raw_bytes, db=db, tenant_id=target.tenant_id, owner_type="client",
        owner_id=target.id, slot=slot, tenant_name=tenant_name,
    )
    filename = file.filename or f"{slot}.jpg"
    stamped_file = UploadFile(
        filename=filename,
        file=io.BytesIO(stamped_bytes),
        size=len(stamped_bytes),
        headers={"content-type": file.content_type or "image/jpeg"},
    )
    try:
        file_ref = await upload_file(file=stamped_file, tenant_id=target.tenant_id, category="compliance")
    except Exception as exc:
        print(f"Document upload failed: {type(exc).__name__}: {exc}")
        raise ServerError(title="Upload Failed", message="Could not store this document.")

    await register_document(
        db, tenant_id=target.tenant_id, owner_type="client", owner_id=target.id,
        slot=slot, file_hash=file_hash, file_ref=file_ref, content_type=file.content_type,
    )
    field_for_slot = {
        "id_front": "id_image_front",
        "id_back": "id_image_back",
        "dl_front": "dl_image_front",
        "driver_id_front": "driver_id_image_front",
        "driver_dl_front": "driver_dl_image_front",
    }
    setattr(target, field_for_slot[slot], file_ref)
    await db.commit()
    return {"slot": slot, "file_ref": file_ref}


# ─── PUBLIC: UPLOAD SELFIE ──────────────────────────────────────────────────

@router.post("/vetting/{token}/upload-selfie", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def upload_vetting_selfie(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    person_type, target = await _resolve_token_target(db, token)
    
    # Enforce image-only for selfie
    assert_allowed_content_type(file.content_type, allow_pdf=False)
    
    raw_bytes = await file.read()
    tenant_name = await _get_tenant_name(db, target.tenant_id)
    
    # Secure ingest
    stamped_bytes, file_hash = await secure_prepare(
        raw_bytes, db=db, tenant_id=target.tenant_id, owner_type=person_type,
        owner_id=target.id, slot="selfie_with_id", tenant_name=tenant_name,
    )
    
    # ✅ FIX: Ensure the filename has a valid image extension for the storage provider
    original_filename = file.filename or "selfie.jpg"
    if not any(original_filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
        original_filename += ".jpg"
    
    # Upload to storage with explicit content-type
    stamped_file = UploadFile(
        filename=original_filename, 
        file=io.BytesIO(stamped_bytes), 
        size=len(stamped_bytes),
        headers={"content-type": file.content_type or "image/jpeg"}
    )
    
    try:
        file_ref = await upload_file(file=stamped_file, tenant_id=target.tenant_id, category="vetting")
    except Exception as e:
        print(f"❌ CRITICAL SELFIE UPLOAD ERROR: {type(e).__name__}: {e}")
        raise ServerError(title="Upload Failed", message="Could not store selfie.")
    
    # Register
    await register_document(
        db, tenant_id=target.tenant_id, owner_type=person_type, owner_id=target.id,
        slot="selfie_with_id", file_hash=file_hash, file_ref=file_ref, content_type=file.content_type,
    )
    
    # Store reference on target
    if person_type == "client":
        target.selfie_with_id_image = file_ref
    else:
        target.selfie_with_id_key = file_ref
        
    await db.commit()
    
    return {"type": "success", "title": "Selfie Received", "message": "Your identity photo was uploaded securely."}


# ─── PUBLIC: SUBMIT ──────────────────────────────────────────────────────────

@router.post("/vetting/{token}/submit", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def submit_vetting(request: Request, token: str, payload: VettingSubmitPayload, db: AsyncSession = Depends(get_db)):
    person_type, target = await _resolve_token_target(db, token)
    
    # Ensure selfie was uploaded
    has_selfie = (person_type == "client" and target.selfie_with_id_image) or \
                 (person_type == "driver" and target.selfie_with_id_key)
    if not has_selfie:
        raise ValidationFailedError(
            title="Missing Selfie",
            message="Please upload your selfie holding your ID before submitting.",
            field_errors={"selfie_with_id": "Required"}
        )

    if person_type == "client":
        missing = missing_client_verification_requirements(target)
        # A sent token is expected at this point; all evidence requirements
        # must still be present before the review queue can receive it.
        missing.pop("verification_status", None)
        if missing:
            raise ValidationFailedError(
                title="Verification Incomplete",
                message="Complete the required documents and driving details before submitting.",
                field_errors=missing,
            )
    
    # Flip status
    if person_type == "client":
        target.verification_status = ClientVerificationStatus.under_review.value
    else:
        target.verification_status = DriverVerificationStatus.under_review.value
        
    # Invalidate token (single-use)
    target.verification_token = None
    target.verification_expires_at = None
    
    await db.commit()
    return {"type": "success", "title": "Submission Received", "message": "Your documents are now under review."}


# ─── ADMIN: REVIEW ───────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/review")
@limiter.limit("10/minute")
async def review_client(
    request: Request,
    client_id: int,
    payload: VettingReviewPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    client = await _resolve_vetting_target(db, "client", client_id, scope.tenant_id)
    
    if client.verification_status != ClientVerificationStatus.under_review.value:
        raise BadRequestError(title="Not Under Review", message="This client is not currently under review.")
        
    if payload.decision == "approve":
        # Approval is the only path to activation. Re-run the full gate here
        # so an incomplete profile can never become active by bypassing the
        # lifecycle endpoint.
        missing = missing_client_verification_requirements(client)
        # The client is under review, not verified yet; ignore that expected
        # transitional state while checking the remaining evidence.
        missing.pop("verification_status", None)
        if missing:
            raise BadRequestError(
                title="Verification Incomplete",
                message="The client still has required verification items missing.",
                field_errors=missing,
            )
        client.verification_status = ClientVerificationStatus.verified.value
        client.verification_token = None
        client.verification_expires_at = None
        client.vetted_at = datetime.now(timezone.utc)
        client.vetted_by = current_user.id
        client.rejection_notes = None
        # ✅ Activate the client upon approval
        if client.status == ClientStatus.pending:
            client.status = ClientStatus.active
    else:
        client.verification_status = ClientVerificationStatus.rejected.value
        client.rejection_notes = payload.rejection_notes
        # Clear selfie so they must retake it on retry
        client.selfie_with_id_image = None
        # Reset token so admin must re-trigger
        client.verification_token = None
        client.verification_expires_at = None
        
    await db.commit()
    return {"type": "success", "message": f"Client {payload.decision}d successfully."}


@router.post("/drivers/{driver_id}/review")
@limiter.limit("10/minute")
async def review_driver(
    request: Request,
    driver_id: int,
    payload: VettingReviewPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    driver = await _resolve_vetting_target(db, "driver", driver_id, scope.tenant_id)
    
    if driver.verification_status != DriverVerificationStatus.under_review.value:
        raise BadRequestError(title="Not Under Review", message="This driver is not currently under review.")
        
    if payload.decision == "approve":
        driver.verification_status = DriverVerificationStatus.verified.value
        driver.verification_token = None
        driver.verification_expires_at = None
        driver.vetted_at = datetime.now(timezone.utc)
        driver.vetted_by = current_user.id
        driver.rejection_notes = None
    else:
        driver.verification_status = DriverVerificationStatus.rejected.value
        driver.rejection_notes = payload.rejection_notes
        driver.selfie_with_id_key = None
        driver.verification_token = None
        driver.verification_expires_at = None
        
    await db.commit()
    return {"type": "success", "message": f"Driver {payload.decision}d successfully."}
