"""Central tenant-scope resolution for request handlers.

Tenant members are always restricted to their own tenant.  A super admin can
inspect the whole platform or deliberately select one tenant for an operation.
Create operations must use ``require_mutation_tenant_scope`` so data is never
created with a NULL tenant id.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Query, status

from app.dependencies.auth import get_current_user
from app.models.users import User, UserRole


@dataclass(frozen=True)
class TenantScope:
    tenant_id: int | None
    is_system_scope: bool


def resolve_tenant_scope(user: User, requested_tenant_id: int | None = None) -> TenantScope:
    """Resolve a safe read scope without trusting caller supplied tenant ids."""
    if user.role == UserRole.super_admin:
        return TenantScope(tenant_id=requested_tenant_id, is_system_scope=requested_tenant_id is None)

    if user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant association",
        )
    if requested_tenant_id is not None and requested_tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access another tenant",
        )
    return TenantScope(tenant_id=user.tenant_id, is_system_scope=False)


async def get_tenant_scope(
    tenant_id: int | None = Query(None, description="Super-admin tenant scope"),
    current_user: User = Depends(get_current_user),
) -> TenantScope:
    return resolve_tenant_scope(current_user, tenant_id)


async def require_mutation_tenant_scope(
    tenant_id: int | None = Query(None, description="Required for super-admin writes"),
    current_user: User = Depends(get_current_user),
) -> TenantScope:
    scope = resolve_tenant_scope(current_user, tenant_id)
    if scope.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Super-admin writes require an explicit tenant_id",
        )
    return scope
