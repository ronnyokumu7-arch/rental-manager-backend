# app/routers/client_invites.py
"""
✅ CLIENT INVITES — single-use onboarding links (tenant + public sides).

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ UPGRADE:
  - Name split: first_name/last_name required; full_name computed server-side.
  - Driving arrangement: self_drive enforces DL image; own_driver creates
    linked personal Driver in same transaction.
  - Document security: sha256 hash + forensic watermark + registry guard
    blocks duplicate documents across people.
  - Cross-entity identity checks prevent same person as client + driver.
  - PDFs accepted for doc slots (id_front, id_back, dl_front); avatar image-only.
"""
import io
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    AppException,
    BadRequestError,
    ConflictError,
    GoneError,
    NotFoundError,
    ServerError,
    ValidationFailedError,
    navigate_action,
)
from app.core.limiter import limiter
from app.db.database import get_db, set_public_rls_context, set_rls_context
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.client_invite import ClientInvite, ClientInviteStatus
from app.models.clients import Client, ClientStatus
from app.models.tenants import Tenant
from app.models.users import User
from app.models.drivers import Driver, DriverEmploymentType, DriverVerificationStatus
from app.schemas.client import ClientOut
from app.schemas.client_invite import (
    ClientIntakeCreate,
    ClientInviteCreate,
    ClientInviteOut,
    PublicInvitePreviewOut,
)
from app.services.client_identity import (
    collect_client_identity_conflicts,
    compute_risk_flags,
)
from app.services.document_security import (
    assert_allowed_content_type,
    hash_bytes,
    register_document,
    secure_prepare,
)
from app.services.storage import upload_file, delete_file

router = APIRouter()

# ✅ Public-side errors send people to the marketing home, not the dashboard
_PUBLIC_HOME = navigate_action("Go Home", "/")

VALID_UPLOAD_FIELDS = {"avatar", "id_front", "id_back", "dl_front"}


# ---------------------------------------------------------------------------
# ✅ SHARED GUARDS
# ---------------------------------------------------------------------------

def _assert_upload_content_type(file: UploadFile, *, allow_pdf: bool) -> None:
    """Content-type guard: docs allow images+PDF; avatar images only."""
    assert_allowed_content_type(file.content_type, allow_pdf=allow_pdf)


async def _upload_public_document(
    file: UploadFile,
    tenant_id: int,
    category: str,
    *,
    db: AsyncSession,
    owner_type: str,
    owner_id: int,
    slot: str,
    tenant_name: str,
) -> str:
    """
    ✅ Secure ingest: hash → duplicate guard → watermark → upload → register.
    Returns the stored URL.
    """
    raw_bytes = await file.read()
    stamped_bytes, file_hash = await secure_prepare(
        raw_bytes,
        db=db,
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        slot=slot,
        tenant_name=tenant_name,
    )
    # Wrap stamped bytes in UploadFile for storage service
    stamped_file = UploadFile(
        filename=file.filename or "document",
        file=io.BytesIO(stamped_bytes),
        size=len(stamped_bytes),
        headers=file.headers,
    )
    try:
        file_url = await upload_file(
            file=stamped_file, tenant_id=tenant_id, category=category
        )
    except AppException:
        raise
    except Exception as e:
        print(f"⚠️ Public upload storage failure for tenant {tenant_id}: {e}")
        raise ServerError(
            title="Upload Failed",
            message="We couldn't store this document. Please try again.",
        )
    # Register in document registry (caller commits)
    await register_document(
        db,
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        slot=slot,
        file_hash=file_hash,
        file_ref=file_url,
        content_type=file.content_type,
    )
    return file_url


def _conflict_error(conflicts, title: str = "Duplicate Client Details") -> ConflictError:
    messages = [c.message for c in conflicts]
    return ConflictError(
        title=title,
        message=messages[0] if messages else "A person with these details already exists.",
        details={"conflicts": messages},
    )


def _invite_live_or_raise(invite) -> None:
    """✅ Shared 404/410 guards for every token-scoped endpoint."""
    if not invite:
        raise NotFoundError(
            title="Invite Not Found",
            message="We couldn't find this invite. Check the link and try again.",
            action=_PUBLIC_HOME,
        )
    if invite.status != ClientInviteStatus.pending:
        raise GoneError(
            title="Invite Already Used or Revoked",
            message="This invite has already been used or was revoked. Ask the agency for a new link.",
            action=_PUBLIC_HOME,
        )
    if invite.is_expired:
        raise GoneError(
            title="Invite Expired",
            message="This invite has expired. Ask the agency for a new link.",
            action=_PUBLIC_HOME,
        )


def _concat_full_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in [first_name.strip(), last_name.strip()] if part)


# ─── TENANT SIDE ────────────────────────────────────────────────────────────

@router.post("/clients/invites", response_model=ClientInviteOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_invite(
    request: Request,
    payload: ClientInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """✅ Generate a single-use onboarding link for this tenant."""
    invite = ClientInvite(
        tenant_id=current_user.tenant_id,
        token=secrets.token_urlsafe(32),
        status=ClientInviteStatus.pending,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.ttl_days),
        expected_name=payload.expected_name,
        expected_phone=payload.expected_phone,
    )
    db.add(invite)
    await db.commit()
    await set_rls_context(db, tenant_id=current_user.tenant_id, user_id=current_user.id)
    await db.refresh(invite)
    return invite


@router.get("/clients/invites", response_model=list[ClientInviteOut])
@limiter.limit("30/minute")
async def list_invites(
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(ClientInvite)
        .where(ClientInvite.tenant_id == current_user.tenant_id)
        .order_by(ClientInvite.created_at.desc())
        .limit(min(limit, 200))
    )
    return (await db.execute(stmt)).scalars().all()


@router.delete("/clients/invites/{invite_id}", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def revoke_invite(
    request: Request,
    invite_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """✅ Kill a live link. Accepted invites cannot be revoked (they're history)."""
    stmt = select(ClientInvite).where(
        ClientInvite.id == invite_id,
        ClientInvite.tenant_id == current_user.tenant_id,
    )
    invite = (await db.execute(stmt)).scalars().first()

    if not invite:
        raise NotFoundError(
            title="Invite Not Found",
            message="We couldn't find this invite. It may have already been removed.",
        )
    if invite.status == ClientInviteStatus.accepted:
        raise BadRequestError(
            title="Invite Already Used",
            message="This invite was already used and cannot be revoked.",
        )

    # ✅ ORPHAN CLEANUP
    uploaded = dict(invite.uploaded_files or {})
    for field, url in uploaded.items():
        try:
            delete_file(url, tenant_id=invite.tenant_id)
        except Exception:
            pass

    invite.status = ClientInviteStatus.revoked
    invite.uploaded_files = None
    await db.commit()
    return {
        "type": "success",
        "title": "Invite Revoked",
        "message": "The onboarding link has been deactivated. Any uploaded files were cleaned up.",
    }


# ── PUBLIC SIDE (no auth) ───────────────────────────────────────────────────

@router.get("/clients/invite/{token}", response_model=PublicInvitePreviewOut)
@limiter.limit("30/minute")
async def preview_invite(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """✅ Branding for the public intake page. Dead links → 410 Gone."""
    await set_public_rls_context(db, token)
    invite = (await db.execute(
        select(ClientInvite).where(ClientInvite.token == token)
    )).scalars().first()

    _invite_live_or_raise(invite)

    await set_rls_context(db, tenant_id=invite.tenant_id)
    stmt = select(ClientInvite).options(
        selectinload(ClientInvite.tenant).selectinload(Tenant.profile)
    ).where(ClientInvite.token == token)
    invite = (await db.execute(stmt)).scalars().unique().first()

    tenant = invite.tenant
    profile = tenant.profile if tenant else None
    return PublicInvitePreviewOut(
        tenant_name=tenant.name if tenant else "the agency",
        tenant_logo_url=profile.logo_url if profile else None,
        tenant_phone=profile.phone if profile else None,
        tenant_email=profile.email if profile else None,
        expires_at=invite.expires_at,
    )


@router.post("/clients/invite/{token}", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def submit_invite(
    request: Request,
    token: str,
    payload: ClientIntakeCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    ✅ Public intake submission.
    """
    await set_public_rls_context(db, token)
    
    # ✅ FIX: Eagerly load tenant to prevent MissingGreenlet lazy-load errors
    stmt = (
        select(ClientInvite)
        .options(selectinload(ClientInvite.tenant))
        .where(ClientInvite.token == token)
        .with_for_update()
    )
    invite = (await db.execute(stmt)).scalars().first()

    _invite_live_or_raise(invite)
    await set_rls_context(db, tenant_id=invite.tenant_id)

    # 1) CROSS-ENTITY IDENTITY CHECKS
    conflicts = await collect_client_identity_conflicts(
        db,
        invite.tenant_id,
        phone=payload.phone,
        email=payload.email,
        id_type=payload.id_type,
        id_number=payload.id_number,
        dl_number=payload.dl_number,
    )
    if conflicts:
        raise _conflict_error(conflicts)

    # 2) SOFT FLAGS
    is_flagged, flag_notes = await compute_risk_flags(
        db,
        invite.tenant_id,
        own_phone=payload.phone,
        next_of_kin_phone=payload.next_of_kin_phone,
    )

    # 3) ARRANGEMENT GUARDS
    if payload.driving_arrangement == "self_drive" and not payload.dl_image_front:
        raise ValidationFailedError(
            title="Driver's Licence Image Required",
            message="Self-drive clients must upload a photo of their driver's licence.",
            field_errors={"dl_image_front": "Required for self-drive arrangement"},
        )

    # 4) CREATE CLIENT
    client_data = payload.model_dump(exclude={"driver"})
    client_data["full_name"] = _concat_full_name(payload.first_name, payload.last_name)

    client = Client(
        tenant_id=invite.tenant_id,
        status=ClientStatus.pending,
        is_flagged=is_flagged,
        flag_notes=flag_notes,
        **client_data,
    )
    db.add(client)

    try:
        await db.flush()

        # 5) OWN DRIVER: create linked Driver record
        if payload.driving_arrangement == "own_driver" and payload.driver:
            block = payload.driver
            driver = Driver(
                tenant_id=invite.tenant_id,
                client_id=client.id,
                full_name=block.full_name,
                phone=block.phone,
                id_number=block.id_number,
                dl_number=block.dl_number,
                dl_expiry=block.dl_expiry,
                dl_issued_date=block.dl_issued_date,
                employment_type=DriverEmploymentType.contracted.value,
                verification_status=DriverVerificationStatus.unverified.value,
            )
            db.add(driver)

        invite.status = ClientInviteStatus.accepted
        invite.accepted_client_id = client.id
        invite.uploaded_files = None
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            title="Client Already Exists",
            message="A client with these details already exists. Contact the agency if this is you.",
            action=_PUBLIC_HOME,
        )

    await set_rls_context(db, tenant_id=client.tenant_id)
    await db.refresh(client)
    return client


# ─── PUBLIC DOCUMENT UPLOADS (Token-Scoped, Secure Ingest) ───────────────────

@router.post("/clients/invite/{token}/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def upload_invite_document(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    field: str = Query(..., description="avatar | id_front | id_back | dl_front"),
    db: AsyncSession = Depends(get_db),
):
    """
    ✅ PUBLIC: Upload a document with forensic stamping + registry guard.
    """
    await set_public_rls_context(db, token)
    
    # ✅ FIX: Eagerly load tenant to prevent MissingGreenlet lazy-load errors
    stmt = select(ClientInvite).options(selectinload(ClientInvite.tenant)).where(ClientInvite.token == token)
    invite = (await db.execute(stmt)).scalars().first()

    _invite_live_or_raise(invite)
    await set_rls_context(db, tenant_id=invite.tenant_id)

    if field not in VALID_UPLOAD_FIELDS:
        raise ValidationFailedError(
            title="Invalid Document Slot",
            message=f"Unknown upload field. Must be one of: {', '.join(sorted(VALID_UPLOAD_FIELDS))}",
            field_errors={"field": "Must be one of: avatar, id_front, id_back, dl_front"},
        )

    # Content-type guard
    allow_pdf = field != "avatar"
    _assert_upload_content_type(file, allow_pdf=allow_pdf)

    category = "avatar" if field == "avatar" else "compliance"

    # Slot map for registry
    slot_map = {
        "avatar": "avatar",
        "id_front": "id_front",
        "id_back": "id_back",
        "dl_front": "dl_front",
    }

    # ✅ Secure ingest: hash → watermark → upload → register
    file_url = await _upload_public_document(
        file,
        tenant_id=invite.tenant_id,
        category=category,
        db=db,
        owner_type="client",
        owner_id=invite.id,  # temporary; re-linked on submit
        slot=slot_map[field],
        tenant_name=invite.tenant.name if invite.tenant else "Agency",
    )

    # ✅ SLOT UPSERT
    uploaded = dict(invite.uploaded_files or {})
    old_url = uploaded.get(field)
    uploaded[field] = file_url
    invite.uploaded_files = uploaded
    await db.commit()

    if old_url and old_url != file_url:
        try:
            delete_file(old_url, tenant_id=invite.tenant_id)
        except Exception:
            pass

    return {
        "type": "success",
        "title": "Document Received",
        "message": "Your document was uploaded successfully.",
        "url": file_url,
        "field": field,
    }
