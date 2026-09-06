# app/routers/tenant_policies.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenant_policies import DEFAULT_POLICY_DOCUMENT, TenantPolicy
from app.models.users import User, UserRole
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.tenant_policy import (
    PolicyDocumentOut,
    TenantPolicyCreate,
    TenantPolicyOut,
    TenantPolicyUpdate,
)
from app.services.business_policy import (
    category_labels,
    default_document,
    get_effective_policy_document,
)
from app.services.cache import invalidate_contract_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/policies", tags=["policies"])

# The Bouncer
tenant_admin_only = Depends(require_role([UserRole.tenant_admin, UserRole.super_admin]))


async def get_authorized_policy_async(policy_id: int, user: User, db: AsyncSession) -> TenantPolicy:
    """Async helper to retrieve policy and enforce ownership/access control."""
    stmt = select(TenantPolicy).where(
        TenantPolicy.id == policy_id,
        TenantPolicy.tenant_id == user.tenant_id,
    )
    result = await db.execute(stmt)
    policy = result.scalars().first()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found"
        )
    return policy


# ---------------------------------------------------------------------------
# ✅ DEFAULTS & EFFECTIVE (merged) — read-only, any authenticated user
# ---------------------------------------------------------------------------
@router.get("/defaults", response_model=PolicyDocumentOut)
@limiter.limit("60/minute")
async def get_default_policies(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """✅ The platform default policy document — what tenants inherit per clause."""
    return {"categories": category_labels(), "document": default_document()}


@router.get("/effective", response_model=PolicyDocumentOut)
@limiter.limit("60/minute")
async def get_effective_policies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """✅ Merged document (defaults + overrides + custom clauses), in contract order."""
    doc = await get_effective_policy_document(db, current_user.tenant_id)
    return {"categories": category_labels(), "document": doc}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("/", response_model=PaginatedResponse[TenantPolicyOut])
@limiter.limit("60/minute")
async def list_policies(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(TenantPolicy).where(
        TenantPolicy.tenant_id == current_user.tenant_id,
    ).order_by(TenantPolicy.category, TenantPolicy.display_order)

    result = await db.execute(stmt)
    policies = result.scalars().all()
    return paginate_items(policies, total=len(policies), page=page, page_size=page_size)


@router.post("/", response_model=TenantPolicyOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_policy(
    request: Request,
    payload: TenantPolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    # ✅ Validate clause_key against the default document (typos ⇒ 422, not orphans)
    if payload.clause_key:
        valid_keys = {
            c["clause_key"] for c in DEFAULT_POLICY_DOCUMENT.get(payload.category, [])
        }
        if payload.clause_key not in valid_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown clause key '{payload.clause_key}' for category '{payload.category.value}'.",
            )

        # ✅ OVERRIDE RULE: one override per default clause — friendly 409
        # (frontend should PATCH the existing row); custom clauses are unlimited.
        existing_stmt = select(TenantPolicy).where(
            TenantPolicy.tenant_id == current_user.tenant_id,
            TenantPolicy.category == payload.category.value,
            TenantPolicy.clause_key == payload.clause_key,
        )
        existing = (await db.execute(existing_stmt)).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This clause is already customized. Update the existing policy instead.",
            )

    policy = TenantPolicy(**payload.model_dump(), tenant_id=current_user.tenant_id)
    db.add(policy)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This clause is already customized. Update the existing policy instead.",
        )
    await db.refresh(policy)

    # ✅ Invalidate contract cache (policies are embedded in contracts)
    await invalidate_contract_cache(current_user.tenant_id)

    # ✅ Log the policy creation
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="create_policy", target_type="tenant_policy", target_id=policy.id,
        details={
            "category": policy.category,
            "clause_key": policy.clause_key,
            "title": policy.title,
        }
    )
    await db.commit()  # Commit the activity log flush

    return policy


@router.patch("/{policy_id}", response_model=TenantPolicyOut)
@limiter.limit("30/minute")
async def update_policy(
    request: Request,
    policy_id: int,
    payload: TenantPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = await get_authorized_policy_async(policy_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    await db.commit()
    await db.refresh(policy)

    # ✅ Invalidate contract cache
    await invalidate_contract_cache(current_user.tenant_id)

    # ✅ Log the policy update
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="update_policy", target_type="tenant_policy", target_id=policy.id,
        details={"changed_fields": list(payload.model_dump(exclude_unset=True).keys())}
    )
    await db.commit()  # Commit the activity log flush

    return policy


@router.post("/{policy_id}/toggle", response_model=TenantPolicyOut)
@limiter.limit("30/minute")
async def toggle_policy(
    request: Request,
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = await get_authorized_policy_async(policy_id, current_user, db)
    policy.is_active = not policy.is_active
    await db.commit()
    await db.refresh(policy)

    # ✅ Invalidate contract cache
    await invalidate_contract_cache(current_user.tenant_id)

    # ✅ Log the policy toggle
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="toggle_policy", target_type="tenant_policy", target_id=policy.id,
        details={"is_active": policy.is_active}
    )
    await db.commit()  # Commit the activity log flush

    return policy


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_policy(
    request: Request,
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = tenant_admin_only,
):
    policy = await get_authorized_policy_async(policy_id, current_user, db)
    await db.delete(policy)
    await db.commit()

    # ✅ Invalidate contract cache
    await invalidate_contract_cache(current_user.tenant_id)

    # ✅ Log the policy deletion
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="delete_policy", target_type="tenant_policy", target_id=policy_id,
        details={}
    )
    await db.commit()  # Commit the activity log flush
