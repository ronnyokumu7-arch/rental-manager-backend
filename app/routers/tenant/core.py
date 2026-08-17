# app/routers/tenants/core.py

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import Tenant, SubscriptionStatus as TenantSubscriptionStatus
from app.models.tenant_profile import TenantProfile
from app.models.users import User, UserRole
from app.models.subscriptions import Subscription, SubscriptionStatus, PlanType, BillingCycle
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantOut
from app.core.security import get_password_hash
from app.services.cache import get_cached_tenant_list, set_cached_tenant_list, invalidate_tenant_cache
from app.services.activity_log import TenantActivityLogger

router = APIRouter()

super_admin_only = Depends(require_role([UserRole.super_admin]))


def _clean_string(value: str | None) -> str | None:
    """Converts empty strings to None to prevent DB unique constraint crashes."""
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None
    return None


@router.post("/", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # 🚨 EXTREMELY STRICT: Heavy atomic provisioning
async def create_tenant(
    request: Request,
    payload: TenantCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    # Sanitize optional string inputs immediately
    phone_number = _clean_string(payload.phone_number)
    kra_pin = _clean_string(payload.kra_pin)
    business_location = _clean_string(payload.business_location)
    admin_phone = _clean_string(payload.admin_phone)
    stripe_customer_id = _clean_string(payload.stripe_customer_id)
    paypal_payer_id = _clean_string(payload.paypal_payer_id)

    # Prevent duplicate email registration (Check BOTH tables)
    existing_tenant_stmt = select(Tenant).where(Tenant.email == payload.email)
    existing_tenant = (await db.execute(existing_tenant_stmt)).scalars().first()
    if existing_tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant with this primary email already exists."
        )

    existing_user_stmt = select(User).where(User.email == payload.admin_email)
    existing_user = (await db.execute(existing_user_stmt)).scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this admin email already exists. Please use a different email."
        )

    try:
        # ✅ RESPECT THE SELECTED PLAN (Don't force free_trial)
        initial_plan_str = payload.plan if payload.plan else "free_trial"

        # Map string to Enum safely
        try:
            initial_plan_enum = PlanType(initial_plan_str)
        except ValueError:
            initial_plan_enum = PlanType.free_trial  # Fallback

        initial_billing_cycle_str = payload.billing_cycle if payload.billing_cycle else "monthly"
        try:
            initial_cycle_enum = BillingCycle(initial_billing_cycle_str)
        except ValueError:
            initial_cycle_enum = BillingCycle.monthly

        # Determine initial status and duration based on plan
        now = datetime.now(timezone.utc)
        ends_at = None

        # ✅ Handle PAYG (30-day trial, then commission accrues)
        if initial_plan_enum == PlanType.pay_as_you_go:
            initial_status = SubscriptionStatus.trial
            duration_days = 30
            ends_at = now + timedelta(days=duration_days)
        elif initial_plan_enum in [PlanType.free_trial, PlanType.starter_trial]:
            initial_status = SubscriptionStatus.trial if initial_plan_enum == PlanType.free_trial else SubscriptionStatus.starter_trial
            duration_days = 30 if initial_plan_enum == PlanType.free_trial else 14
            ends_at = now + timedelta(days=duration_days)
        else:
            # Paid monthly plan selected during onboarding. Needs payment verification.
            initial_status = SubscriptionStatus.pending_verification

        # 1. Create Core Tenant Record
        tenant = Tenant(
            name=payload.name.strip(),
            email=payload.email.strip(),
            phone_number=phone_number,
            admin_name=(payload.admin_name or payload.name).strip(),
            admin_email=payload.admin_email.strip(),
            admin_phone=admin_phone or phone_number,
            plan=initial_plan_str,
            billing_cycle=initial_billing_cycle_str,
            auto_renew=payload.auto_renew,
            subscription_status=initial_status,
            default_payment_method=payload.default_payment_method,
            stripe_customer_id=stripe_customer_id,
            paypal_payer_id=paypal_payer_id,
            payment_metadata=payload.payment_metadata or {},
            is_active=True,
            is_archived=False,
        )
        db.add(tenant)
        await db.flush()  # Generates tenant.id without committing yet

        # ✅ 2. ATOMICALLY CREATE SUBSCRIPTION RECORD (Respects the selected plan)
        new_subscription = Subscription(
            tenant_id=tenant.id,
            plan=initial_plan_enum,
            billing_cycle=initial_cycle_enum,
            status=initial_status,
            starts_at=now,
            ends_at=ends_at,
            auto_renew=payload.auto_renew,
            created_at=now,
            updated_at=now,
        )
        db.add(new_subscription)

        # Sync trial date to Tenant model for quick lookups
        tenant.trial_ends_at = ends_at if initial_status in [SubscriptionStatus.trial, SubscriptionStatus.starter_trial] else None

        # 3. Auto-provision TenantProfile
        contract_prefix = f"T{tenant.id:04d}"
        profile = TenantProfile(
            tenant_id=tenant.id,
            company_name=payload.name.strip(),
            address=business_location,
            phone=phone_number,
            email=payload.email.strip(),
            tax_number=kra_pin.upper() if kra_pin else None,
            contract_prefix=contract_prefix,
        )
        db.add(profile)

        # 4. Auto-provision Initial Tenant Admin User (AGENCY OWNER)
        admin_user = User(
            email=payload.admin_email.strip(),
            full_name=(payload.admin_name or payload.name).strip(),
            phone_number=admin_phone or phone_number,
            password_hash=get_password_hash(payload.password),
            role=UserRole.tenant_admin,
            tenant_id=tenant.id,
            is_active=True,
            is_onboarded=True,
            email_verified=True,
            phone_verified=True,
        )
        db.add(admin_user)
        await db.flush()  # Generates admin_user.id

        # LINK AGENCY OWNER TO TENANT
        tenant.owner_id = admin_user.id

        # 5. Commit EVERYTHING atomically. If anything above fails, it all rolls back.
        await db.commit()

        # ✅ 6. Eager re-fetch so Pydantic serialization can NEVER lazy-load
        # (this replaces the old db.refresh(tenant.profile) which could raise
        #  MissingGreenlet AFTER the commit → the "tenant exists but UI shows error" bug)
        stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant.id)
        tenant = (await db.execute(stmt)).scalars().first()

        # ✅ 7. Post-commit side effects must NEVER fail the response.
        # The tenant already exists — a cache/log failure is a warning, not a 500.
        try:
            await invalidate_tenant_cache()
        except Exception as cache_err:
            print(f"⚠️ Cache invalidation warning (tenant created): {cache_err}")

        try:
            await TenantActivityLogger.on_created(db, current_user.id, tenant)
            await db.commit()
        except Exception as log_err:
            await db.rollback()
            print(f"⚠️ Activity log warning (tenant created): {log_err}")

        return tenant

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A database constraint was violated. This email or tax ID might already be registered."
        )
    except Exception as e:
        await db.rollback()
        print(f"🚨 create_tenant failed BEFORE commit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision tenant environment: {str(e)}"
        )


@router.get("/", response_model=PaginatedResponse[TenantOut])
@limiter.limit("60/minute")
async def list_tenants(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None, description="Search by name or KRA PIN"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by ACTIVE or SUSPENDED"),
    show_archived: bool = Query(False, description="Include archived/vaulted tenants"),
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    # ✅ Check cache first (keyed by all filter parameters)
    cached = await get_cached_tenant_list(
        skip=(page - 1) * page_size,
        limit=page_size,
        search=search,
        status_filter=status_filter,
        show_archived=show_archived,
    )
    if cached is not None:
        return paginate_items(cached, total=len(cached), page=page, page_size=page_size)

    stmt = select(Tenant)

    if search:
        search_term = f"%{search}%"
        # ✅ Async subquery for search
        search_subq = select(Tenant.id).join(TenantProfile).where(
            or_(
                Tenant.name.ilike(search_term),
                TenantProfile.tax_number.ilike(search_term)
            )
        ).subquery()
        stmt = stmt.where(Tenant.id.in_(search_subq))

    # Multi-tenancy & Vault Enforcement
    if not show_archived:
        stmt = stmt.where(Tenant.is_archived == False)

    if status_filter == "ACTIVE":
        stmt = stmt.where(Tenant.is_active == True)
    elif status_filter == "SUSPENDED":
        stmt = stmt.where(Tenant.is_active == False)

    # ✅ Eager load profile using selectinload (required for async)
    stmt = stmt.options(selectinload(Tenant.profile))

    result = await db.execute(stmt)
    tenants = result.scalars().all()

    # ✅ Write to cache
    await set_cached_tenant_list(
        skip=(page - 1) * page_size,
        limit=page_size,
        search=search,
        status_filter=status_filter,
        show_archived=show_archived,
        tenants=tenants,
    )

    return paginate_items(tenants, total=len(tenants), page=page, page_size=page_size)


@router.get("/{tenant_id}", response_model=TenantOut)
@limiter.limit("60/minute")
async def get_tenant(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full details for a single tenant by ID."""

    # Security Check: Super admins can see any tenant. Regular users can only see their own.
    if current_user.role != UserRole.super_admin and current_user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this tenant."
        )

    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return tenant


@router.patch("/{tenant_id}", response_model=TenantOut)
@limiter.limit("20/minute")
async def update_tenant(
    request: Request,
    tenant_id: int,
    payload: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()

    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)

    # ✅ FIXED: Sync TenantProfile.company_name with Tenant.name (same commit).
    # Profile is already eager-loaded via selectinload above.
    # Keeps PDFs / public views / topbar consistent when a super admin renames a tenant.
    if "name" in update_data and tenant.profile:
        tenant.profile.company_name = tenant.name

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update failed due to a unique constraint violation."
        )

    # ✅ Eager re-fetch (no lazy loads after commit)
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    tenant = (await db.execute(stmt)).scalars().unique().first()

    # ✅ Post-commit side effects must NEVER fail the response
    try:
        await invalidate_tenant_cache()
    except Exception as cache_err:
        print(f"⚠️ Cache invalidation warning (tenant updated): {cache_err}")

    try:
        await TenantActivityLogger.on_updated(db, current_user.id, tenant, list(update_data.keys()))
        await db.commit()
    except Exception as log_err:
        await db.rollback()
        print(f"⚠️ Activity log warning (tenant updated): {log_err}")

    return tenant
