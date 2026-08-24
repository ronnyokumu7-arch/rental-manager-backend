# app/routers/client_invites.py
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.client_invite import ClientInvite, ClientInviteStatus
from app.models.clients import Client, ClientStatus
from app.models.tenants import Tenant
from app.models.users import User
from app.schemas.client import ClientOut
from app.schemas.client_invite import (
    ClientIntakeCreate,
    ClientInviteCreate,
    ClientInviteOut,
    PublicInvitePreviewOut,
)
from app.services.client_identity import check_identity_conflicts, compute_risk_flags
from app.services.storage import upload_file, delete_file

router = APIRouter()


# ─── TENANT SIDE ─────────────────────────────────────────────────────────────

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
        # ✅ OPTIONAL: who the tenant is expecting (informational only)
        expected_name=payload.expected_name,
        expected_phone=payload.expected_phone,
    )
    db.add(invite)
    await db.commit()
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
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status == ClientInviteStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite was already used and cannot be revoked.",
        )

    # ✅ ORPHAN CLEANUP: the client never completed onboarding, so any files
    # uploaded against this live link are orphans. Delete them from storage.
    uploaded = dict(invite.uploaded_files or {})
    for field, url in uploaded.items():
        try:
            delete_file(url, tenant_id=invite.tenant_id)
        except Exception:
            pass  # idempotent — storage may already be gone

    invite.status = ClientInviteStatus.revoked
    invite.uploaded_files = None
    await db.commit()
    return {"message": "Invite revoked."}


# ─── PUBLIC SIDE (no auth) ───────────────────────────────────────────────────

@router.get("/clients/invite/{token}", response_model=PublicInvitePreviewOut)
@limiter.limit("30/minute")
async def preview_invite(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """✅ Branding for the public intake page. Dead links → 410 Gone."""
    stmt = select(ClientInvite).options(
        selectinload(ClientInvite.tenant).selectinload(Tenant.profile)
    ).where(ClientInvite.token == token)
    invite = (await db.execute(stmt)).scalars().unique().first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status != ClientInviteStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invite has already been used or was revoked.",
        )
    if invite.is_expired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This invite has expired.",
        )

    tenant = invite.tenant
    profile = tenant.profile if tenant else None
    return PublicInvitePreviewOut(
        tenant_name=tenant.name if tenant else "the agency",
        tenant_logo_url=profile.logo_url if profile else None,
        tenant_phone=profile.phone if tenant else None,
        tenant_email=profile.email if tenant else None,
        expires_at=invite.expires_at,
    )


@router.post("/clients/invite/{token}", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")  # 🚨 STRICT: public self-onboarding
async def submit_invite(
    request: Request,
    token: str,
    payload: ClientIntakeCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    ✅ Public intake submission.
    - Hard blocks (identity conflicts) → 409
    - Soft flags (F1/F2) → stored, never block
    - status hardcoded to pending; invite flipped accepted atomically
    - Document URLs from prior uploads are stored on the client record
    """
    # FOR UPDATE: two simultaneous submits can't both consume the invite
    stmt = select(ClientInvite).where(ClientInvite.token == token).with_for_update()
    invite = (await db.execute(stmt)).scalars().first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status != ClientInviteStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invite has already been used or was revoked.",
        )
    if invite.is_expired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This invite has expired.",
        )

    # 1) HARD BLOCKS (per-tenant identity uniqueness)
    conflicts = await check_identity_conflicts(
        db,
        invite.tenant_id,
        phone=payload.phone,
        email=payload.email,
        id_type=payload.id_type,
        id_number=payload.id_number,
        dl_number=payload.dl_number,
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[c.message for c in conflicts],
        )

    # 2) SOFT FLAGS (suspicion only — never blocks)
    is_flagged, flag_notes = await compute_risk_flags(
        db,
        invite.tenant_id,
        own_phone=payload.phone,
        next_of_kin_phone=payload.next_of_kin_phone,
    )

    # 3) CREATE CLIENT — status forced to pending, server-side
    client = Client(
        tenant_id=invite.tenant_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        id_type=payload.id_type,
        id_number=payload.id_number,
        dl_number=payload.dl_number,
        dl_expiry=payload.dl_expiry,
        residential_address=payload.residential_address,
        work_address=payload.work_address,
        next_of_kin_name=payload.next_of_kin_name,
        next_of_kin_phone=payload.next_of_kin_phone,
        status=ClientStatus.pending,   # ✅ NEVER trust the client
        is_flagged=is_flagged,
        flag_notes=flag_notes,
        # ✅ Store uploaded document URLs (now real schema fields)
        avatar_image=payload.avatar_image,
        id_image_front=payload.id_image_front,
        id_image_back=payload.id_image_back,
        dl_image_front=payload.dl_front,
    )
    db.add(client)

    try:
        await db.flush()  # get client.id without committing yet
        invite.status = ClientInviteStatus.accepted
        invite.accepted_client_id = client.id
        # ✅ Clear upload tracking — URLs are now owned by the Client record
        invite.uploaded_files = None
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A client with these details already exists.",
        )

    await db.refresh(client)
    return client


# ─── PUBLIC DOCUMENT UPLOADS (Token-Scoped, Slot-Upsert) ────────────────────

@router.post("/clients/invite/{token}/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")  # 🚨 STRICT: public upload abuse prevention
async def upload_invite_document(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    field: str = Query(..., description="avatar | id_front | id_back | dl_front"),
    db: AsyncSession = Depends(get_db),
):
    """
    ✅ PUBLIC: Upload a document while the invite is live.

    ✅ SLOT UPSERT: only one file per (invite, field) can exist.
    Re-uploading a slot atomically deletes the replaced file from storage
    before storing the new one. Clients can retry freely without accumulating
    orphan files — the invite's `uploaded_files` JSONB tracks the active URL.
    """
    # Validate invite is live
    stmt = select(ClientInvite).where(ClientInvite.token == token)
    invite = (await db.execute(stmt)).scalars().first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status != ClientInviteStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invite has already been used or was revoked.",
        )
    if invite.is_expired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This invite has expired.",
        )

    # Validate field
    valid_fields = {"avatar", "id_front", "id_back", "dl_front"}
    if field not in valid_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid field. Must be one of: {', '.join(sorted(valid_fields))}",
        )

    # Map field to category
    category = "avatar" if field == "avatar" else "compliance"

    # ✅ Upload using the secure multi-tenant storage service (compression pipeline)
    file_url = await upload_file(
        file=file,
        tenant_id=invite.tenant_id,
        category=category
    )

    # ✅ SLOT UPSERT: delete the replaced file AFTER successful new upload.
    # If upload failed (exception above), the old file stays — never lose data.
    uploaded = dict(invite.uploaded_files or {})
    old_url = uploaded.get(field)
    uploaded[field] = file_url
    invite.uploaded_files = uploaded
    await db.commit()

    if old_url and old_url != file_url:
        try:
            delete_file(old_url, tenant_id=invite.tenant_id)
        except Exception:
            pass  # idempotent — storage may already be gone

    return {"url": file_url, "field": field}
