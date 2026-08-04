# app/routers/vault/tenants.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import Tenant, SubscriptionStatus
from app.models.users import User, UserRole
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.tenant import TenantOut
from app.services.cache import invalidate_tenant_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/tenants", tags=["vault-tenants"])

# 🔒 Security: Only Super Admins can manage the Tenant Vault
super_admin_only = Depends(require_role([UserRole.super_admin]))

@router.get("/", response_model=PaginatedResponse[TenantOut])
@limiter.limit("60/minute")
async def list_vault_tenants(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    # Fetch tenants that are archived, cancelled, or inactive
    stmt = select(Tenant).options(
        selectinload(Tenant.profile)
    ).where(
        or_(
            Tenant.is_archived == True,
            Tenant.subscription_status == SubscriptionStatus.cancelled,
            Tenant.is_active == False
        )
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            Tenant.name.ilike(search_lower) |
            Tenant.email.ilike(search_lower) |
            Tenant.admin_name.ilike(search_lower)
        )
        
    stmt = stmt.order_by(Tenant.updated_at.desc())
    
    result = await db.execute(stmt)
    tenants = result.scalars().all()
    return paginate_items(tenants, total=len(tenants), page=page, page_size=page_size)

@router.post("/{tenant_id}/restore", response_model=TenantOut)
@limiter.limit("10/minute")
async def restore_vault_tenant(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found in vault")
        
    # Restore logic: Reactivate the agency
    tenant.is_archived = False
    tenant.is_active = True
    tenant.suspension_reason = None
    tenant.suspended_at = None
    
    # If it was cancelled, bring it back to an active state
    if tenant.subscription_status == SubscriptionStatus.cancelled:
        tenant.subscription_status = SubscriptionStatus.active
        
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    # ✅ Invalidate tenant cache so it appears in active lists
    await invalidate_tenant_cache()
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=tenant.id, user_id=current_user.id,
        action="restore_tenant", target_type="tenant", target_id=tenant.id,
        details={"tenant_name": tenant.name}
    )
    await db.commit()  # Commit the activity log flush

    return tenant

@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_tenant(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found in vault")
        
    # Capture details before permanent deletion (object becomes detached after delete)
    tenant_name = tenant.name
    tenant_id_for_log = tenant.id
        
    # Hard delete: Permanent destruction from the database
    # Note: Because of cascade="all, delete-orphan" on the Tenant model, 
    # this will also permanently delete all associated users, bookings, vehicles, etc.
    await db.delete(tenant)
    await db.commit()

    # ✅ Invalidate tenant cache
    await invalidate_tenant_cache()
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=tenant_id_for_log, user_id=current_user.id,
        action="hard_delete_tenant", target_type="tenant", target_id=tenant_id_for_log,
        details={"tenant_name": tenant_name}
    )
    await db.commit()  # Commit the activity log flush
