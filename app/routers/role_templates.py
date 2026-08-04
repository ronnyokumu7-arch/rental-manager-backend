# app/routers/role_templates.py

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.models.role_template import RoleTemplate
from app.schemas.role_template import RoleTemplateOut, RoleTemplateUpdate
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.core.permissions import PERMISSION_CATEGORIES
from app.services.cache import invalidate_user_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/role-templates", tags=["role_templates"])

# Clean dependency for cleaner endpoint signatures
admin_or_super = Depends(require_role([UserRole.tenant_admin, UserRole.super_admin]))

@router.get("/matrix")
@limiter.limit("120/minute")  # Static data, safe to allow higher read limit
async def get_permission_matrix(
    request: Request,
    current_user: User = admin_or_super,
):
    """Returns the master dictionary of all possible permissions for the UI to render."""
    return PERMISSION_CATEGORIES

@router.get("/", response_model=PaginatedResponse[RoleTemplateOut])
@limiter.limit("60/minute")
async def list_templates(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_super,
):
    """Returns all role templates for the current tenant."""
    stmt = select(RoleTemplate).where(RoleTemplate.tenant_id == current_user.tenant_id)
    result = await db.execute(stmt)
    templates = result.scalars().all()
    return paginate_items(templates, total=len(templates), page=page, page_size=page_size)

@router.patch("/{template_id}", response_model=RoleTemplateOut)
@limiter.limit("30/minute")
async def update_template(
    request: Request,
    template_id: int,
    payload: RoleTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_super,
):
    """Updates the default permissions for a specific job title."""
    stmt = select(RoleTemplate).where(
        RoleTemplate.id == template_id,
        RoleTemplate.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    template = result.scalars().first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    template.permissions = payload.permissions
    await db.commit()
    await db.refresh(template)

    # ✅ Invalidate user cache (changing a template affects users with this role)
    if current_user.tenant_id:
        await invalidate_user_cache(current_user.tenant_id)
        
    # ✅ Log the template update
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id or 0, user_id=current_user.id,
        action="update_role_template", target_type="role_template", target_id=template.id,
        details={"job_title": template.job_title, "permission_count": len(payload.permissions)}
    )
    await db.commit()  # Commit the activity log flush

    return template
