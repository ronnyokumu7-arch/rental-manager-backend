# app/routers/tenants/lifecycle.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.tenant import TenantOut
from app.services.cache import invalidate_tenant_cache
from app.services.activity_log import TenantActivityLogger

router = APIRouter()

super_admin_only = Depends(require_role([UserRole.super_admin]))


@router.post("/{tenant_id}/suspend", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Locks an entire agency out
async def suspend_tenant(
    request: Request,
    tenant_id: int,
    reason: str | None = "Administrative Action",
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # ✅ FIX: Actually assign the reason to the model field
    tenant.is_active = False
    tenant.suspension_reason = reason
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    # ✅ Invalidate tenant cache and log the suspension
    await invalidate_tenant_cache()
    await TenantActivityLogger.on_suspended(db, current_user.id, tenant, reason or "Administrative Action")
    await db.commit()  # Commit the activity log flush

    return tenant


@router.post("/{tenant_id}/activate", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Restores agency access
async def activate_tenant(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    tenant.is_active = True
    tenant.suspension_reason = None  # Clear reason on reactivation
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    # ✅ Invalidate tenant cache and log the activation
    await invalidate_tenant_cache()
    await TenantActivityLogger.on_activated(db, current_user.id, tenant)
    await db.commit()  # Commit the activity log flush

    return tenant


@router.post("/{tenant_id}/archive", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Moves tenant to vault
async def archive_tenant(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """Moves tenant to Vault (Soft Delete)"""
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    tenant.is_archived = True
    tenant.is_active = False
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    # ✅ Invalidate tenant cache and log the archival
    await invalidate_tenant_cache()
    await TenantActivityLogger.on_archived(db, current_user.id, tenant)
    await db.commit()  # Commit the activity log flush

    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")  # 🚨 EXTREMELY STRICT: Destructive action
async def delete_tenant(
    request: Request,
    tenant_id: int,
    hard_delete: bool = Query(False, description="Permanently remove from DB instead of archiving"),
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # ✅ Capture tenant details BEFORE deletion (object becomes detached after db.delete)
    tenant_name = tenant.name
    tenant_id_for_log = tenant.id

    if hard_delete:
        await db.delete(tenant)
        await db.commit()
    else:
        # Default behavior is soft delete / archive
        tenant.is_archived = True
        tenant.is_active = False
        await db.commit()

    # ✅ Always invalidate tenant cache
    await invalidate_tenant_cache()

    # ✅ Log the deletion (uses pre-captured details to avoid accessing detached object)
    await TenantActivityLogger.on_deleted(
        db, current_user.id, tenant_id_for_log, tenant_name, hard_delete
    )
    await db.commit()  # Commit the activity log flush
