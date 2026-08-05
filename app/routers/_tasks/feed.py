from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.models.task import Task, TaskStatus
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.schemas.task import TaskOut
from app.services.cache import get_cached_task_list, set_cached_task_list

router = APIRouter()

admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))


@router.get("/my-tasks", response_model=PaginatedResponse[TaskOut])
@limiter.limit("60/minute")
async def get_my_tasks(
    request: Request,
    status: Optional[TaskStatus] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # ✅ 1. Check cache first
    cached = await get_cached_task_list(
        tenant_id=None if current_user.role == UserRole.super_admin else current_user.tenant_id,
        user_id=current_user.id,
        status=status.value if status else None,
        category=category
    )
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    # ✅ 2. Cache miss: Query DB
    stmt = select(Task).where(Task.is_archived == False)
    
    if current_user.role == UserRole.super_admin:
        pass  # Super admins see all tasks across all tenants
    elif current_user.role == UserRole.tenant_admin:
        stmt = stmt.where(Task.tenant_id == current_user.tenant_id)
    else:
        # Staff only see tasks assigned to them
        stmt = stmt.where(
            Task.tenant_id == current_user.tenant_id,
            Task.user_id == current_user.id
        )
        
    if status: 
        stmt = stmt.where(Task.status == status)
    if category: 
        stmt = stmt.where(Task.category == category)
        
    stmt = stmt.order_by(Task.due_date.asc(), Task.priority.desc())
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    # ✅ 3. Write to cache
    await set_cached_task_list(
        tenant_id=None if current_user.role == UserRole.super_admin else current_user.tenant_id,
        user_id=current_user.id,
        status=status.value if status else None,
        category=category,
        tasks=tasks
    )
    
    return paginate_items(tasks, total=len(tasks), page=page, page_size=page_size)


@router.get("/user/{user_id}", response_model=PaginatedResponse[TaskOut])
@limiter.limit("60/minute")
async def get_user_tasks(
    request: Request,
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above
):
    # ✅ 1. Check cache first (using user_id as key)
    cached = await get_cached_task_list(
        tenant_id=None if current_user.role == UserRole.super_admin else current_user.tenant_id,
        user_id=user_id,
        status=None,
        category=None
    )
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    # ✅ 2. Cache miss: Query DB
    tenant_filter = Task.tenant_id == current_user.tenant_id if current_user.tenant_id else True
    
    stmt = select(Task).where(
        tenant_filter,
        Task.user_id == user_id,
        Task.is_archived == False
    ).order_by(Task.due_date.asc(), Task.priority.desc())
    
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    # ✅ 3. Write to cache
    await set_cached_task_list(
        tenant_id=None if current_user.role == UserRole.super_admin else current_user.tenant_id,
        user_id=user_id,
        status=None,
        category=None,
        tasks=tasks
    )
    
    return paginate_items(tasks, total=len(tasks), page=page, page_size=page_size)


@router.get("/unassigned", response_model=PaginatedResponse[TaskOut])
@limiter.limit("60/minute")
async def get_unassigned_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above
):
    # ✅ 1. Check cache first (using 0 as dummy user_id for unassigned pool)
    cached = await get_cached_task_list(
        tenant_id=None if current_user.role == UserRole.super_admin else current_user.tenant_id,
        user_id=0, 
        status=TaskStatus.unassigned.value,
        category=None
    )
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    # ✅ 2. Cache miss: Query DB
    tenant_filter = Task.tenant_id == current_user.tenant_id if current_user.tenant_id else True
    
    stmt = select(Task).where(
        tenant_filter,
        Task.user_id == None,
        Task.status == TaskStatus.unassigned,
        Task.is_archived == False
    ).order_by(Task.created_at.desc())
    
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    # ✅ 3. Write to cache
    await set_cached_task_list(
        tenant_id=None if current_user.role == UserRole.super_admin else current_user.tenant_id,
        user_id=0,
        status=TaskStatus.unassigned.value,
        category=None,
        tasks=tasks
    )
    
    return paginate_items(tasks, total=len(tasks), page=page, page_size=page_size)
