from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.tenants import Tenant
from app.models.users import UserRole

from app.db.database import get_db, set_public_rls_context, set_rls_context
from app.core.limiter import limiter
from app.core.security import get_password_hash, normalize_email
from app.models.users import User
from app.schemas.user import UserOut, AcceptInvitePayload, UserInvitePreviewOut
from app.services.cache import invalidate_user_cache
from app.services.activity_log import ActivityLogService
from app.services.storage import upload_file

router = APIRouter()


@router.post("/invite/{token}/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def upload_invite_document(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    field: str = Query(..., description="avatar | id_front | dl_front"),
    db: AsyncSession = Depends(get_db),
):
    """Upload a staff invite document before the invite is accepted."""
    await set_public_rls_context(db, token)
    user = (await db.execute(
        select(User).where(User.invite_token == token)
    )).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Invite not found")
    if user.is_onboarded:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invite has already been used.")
    if user.invite_expires_at and user.invite_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invite has expired.")
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite has no tenant context")

    await set_rls_context(db, tenant_id=user.tenant_id, public_user_id=user.id)
    field_categories = {"avatar": "avatar", "id_front": "compliance", "dl_front": "compliance"}
    category = field_categories.get(field)
    if category is None:
        raise HTTPException(status_code=400, detail="Invalid upload field")

    file_url = await upload_file(file=file, tenant_id=user.tenant_id, category=category)
    return {"url": file_url, "field": field}


def _validate_file_url_belongs_to_tenant(file_url: str | None, tenant_id: int) -> None:
    """
    ✅ CRITICAL: Validate that a file URL belongs to the specified tenant.
    Prevents cross-tenant file injection attacks.
    """
    if not file_url:
        return  # None is allowed (optional fields)
    
    if file_url.startswith("/api/v1/files/"):
        pass
    elif file_url.startswith("http://") or file_url.startswith("https://"):
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file URL format"
        )


@router.post("/accept-invite", response_model=UserOut)
@limiter.limit("10/minute")
async def accept_invite(
    request: Request,
    payload: AcceptInvitePayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Allows a user to accept an invite by providing their token and setting a password.
    This flips is_onboarded to True and clears the invite token.
    """
    await set_public_rls_context(db, payload.invite_token)
    # 1. Find user by token
    stmt = select(User).where(User.invite_token == payload.invite_token)
    user = (await db.execute(stmt)).scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite token")
    await set_rls_context(db, tenant_id=user.tenant_id, public_user_id=user.id)

    # 2. Check expiration
    if user.invite_expires_at and user.invite_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite token has expired")

    # 3. Check if already onboarded
    if user.is_onboarded:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already active")

    # ✅ CRITICAL: Validate all file URLs belong to the user's tenant
    _validate_file_url_belongs_to_tenant(payload.avatar_url, user.tenant_id or 0)
    _validate_file_url_belongs_to_tenant(payload.id_image_url, user.tenant_id or 0)
    _validate_file_url_belongs_to_tenant(payload.dl_image_url, user.tenant_id or 0)

    # 4. Conditional Validation for Drivers
    if user.job_title and user.job_title.lower() == "driver":
        if not payload.dl_number:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Driver's License Number is required for Drivers.")
        if not payload.dl_image_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Driver's License Image is required for Drivers.")

    # 5. Map Identity & Compliance Fields
    user.full_name = payload.full_name
    user.phone_number = payload.phone_number
    user.avatar_url = payload.avatar_url
    
    user.id_number = payload.id_number
    user.id_image_url = payload.id_image_url
    user.dl_number = payload.dl_number
    user.dl_image_url = payload.dl_image_url
    user.dl_expiry = payload.dl_expiry

    # ✅ NEW: Map Financial / Payout Details (For Investors)
    user.mpesa_phone = payload.mpesa_phone
    user.bank_name = payload.bank_name
    user.bank_account_number = payload.bank_account_number
    user.bank_account_name = payload.bank_account_name

    # ✅ SECURITY FIX: Handle email updates safely
    normalized_email = normalize_email(payload.email)
    if normalized_email != user.email:
        existing_user_stmt = select(User).where(User.email == normalized_email)
        existing_user = (await db.execute(existing_user_stmt)).scalars().first()
        if existing_user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This email is already in use by another account")
        user.email = normalized_email

    # 6. Update user state (Password & Onboarding Status)
    user.password_hash = get_password_hash(payload.password)
    user.is_onboarded = True
    user.invite_token = None    # Invalidate the token so it can't be reused
    user.invite_expires_at = None
    
    await db.commit()
    await set_rls_context(db, tenant_id=user.tenant_id, public_user_id=user.id)
    await db.refresh(user)

    # ✅ Invalidate cache and log the onboarding completion
    if user.tenant_id:
        await invalidate_user_cache(user.tenant_id)
    await set_rls_context(db, tenant_id=user.tenant_id, public_user_id=user.id)

    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=user.id,
        action="accept_invite", target_type="user", target_id=user.id,
        details={"user_email": user.email, "job_title": user.job_title, "role": user.role.value}
    )
    await db.commit()  # Commit the activity log flush

    return user


@router.get("/invite/{token}/preview", response_model=UserInvitePreviewOut)
@limiter.limit("30/minute")
async def preview_user_invite(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """✅ Branding & role preview for the public user onboarding page. Dead links → 410 Gone."""
    await set_public_rls_context(db, token)
    user = (await db.execute(
        select(User).where(User.invite_token == token)
    )).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Invite not found")
    await set_rls_context(db, tenant_id=user.tenant_id, public_user_id=user.id)
    
    stmt = select(User).options(
        selectinload(User.tenant).selectinload(Tenant.profile)
    ).where(User.invite_token == token)
    user = (await db.execute(stmt)).scalars().unique().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    
    if user.is_onboarded:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This account has already been set up.",
        )
        
    if user.invite_expires_at and user.invite_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE, 
            detail="This invite has expired.",
        )

    tenant = user.tenant
    profile = tenant.profile if tenant and hasattr(tenant, 'profile') else None
    
    # Derive flags for the frontend
    is_driver = bool(user.job_title and user.job_title.lower() == "driver")
    is_investor = user.role.value == "investor"  # ✅ NEW: Check if role is investor

    return UserInvitePreviewOut(
        tenant_name=tenant.name if tenant else "the platform",
        tenant_logo_url=profile.logo_url if profile else None,
        tenant_phone=profile.phone if profile else None,
        tenant_email=profile.email if profile else None,
        expires_at=user.invite_expires_at,
        expected_full_name=user.full_name,
        expected_email=user.email,
        department=user.department,
        job_title=user.job_title,
        role=user.role,
        is_driver=is_driver,
        is_investor=is_investor,  # ✅ NEW: Pass flag to frontend
    )
