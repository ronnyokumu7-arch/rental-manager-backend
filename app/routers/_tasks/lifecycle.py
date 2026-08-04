from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.models.task import Task, TaskStatus
from app.schemas.task import TaskOut, TaskUpdate
from app.services.cache import invalidate_task_cache
from app.services.activity_log import ActivityLogService

router = APIRouter()

admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))


@router.patch("/{task_id}/claim", response_model=TaskOut)
@limiter.limit("30/minute")
async def claim_task(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    tenant_filter = Task.tenant_id == current_user.tenant_id if current_user.tenant_id else True
    
    stmt = select(Task).where(
        Task.id == task_id,
        tenant_filter,
        Task.user_id == None,
        Task.status == TaskStatus.unassigned
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or already claimed")
    
    task.user_id = current_user.id
    task.status = TaskStatus.pending
    await db.commit()
    await db.refresh(task)

    # ✅ Invalidate task caches (claimer's feed and the unassigned pool)
    await invalidate_task_cache(task.tenant_id, current_user.id)
    await invalidate_task_cache(task.tenant_id, 0)  # 0 represents the unassigned pool cache key
    
    # ✅ Log the claim action
    await ActivityLogService.log(
        db=db, tenant_id=task.tenant_id, user_id=current_user.id,
        action="claim_task", target_type="task", target_id=task.id,
        details={"task_title": task.title}
    )
    await db.commit()  # Commit the activity log flush

    return task


@router.patch("/{task_id}/assign", response_model=TaskOut)
@limiter.limit("30/minute")
async def assign_task(
    request: Request,
    task_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above
):
    if "user_id" not in payload:
        raise HTTPException(status_code=400, detail="user_id is required")
    
    tenant_filter = Task.tenant_id == current_user.tenant_id if current_user.tenant_id else True
    
    stmt = select(Task).where(
        Task.id == task_id,
        tenant_filter
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # The task's tenant, rather than the actor's tenant, is authoritative.
    # This lets the system owner assign work in any agency without allowing
    # tenant admins to cross their own boundary.
    target_stmt = select(User).where(
        User.id == payload["user_id"],
        User.tenant_id == task.tenant_id
    )
    target_result = await db.execute(target_stmt)
    target_user = target_result.scalars().first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found in your agency")
        
    task.user_id = target_user.id
    task.status = TaskStatus.pending
    task.requires_role = None
    await db.commit()
    await db.refresh(task)

    # ✅ Invalidate all task caches to ensure consistency across users
    await invalidate_task_cache(task.tenant_id)
    
    # ✅ Log the assignment action
    await ActivityLogService.log(
        db=db, tenant_id=task.tenant_id, user_id=current_user.id,
        action="assign_task", target_type="task", target_id=task.id,
        details={"task_title": task.title, "assigned_to_user_id": target_user.id}
    )
    await db.commit()  # Commit the activity log flush

    return task


@router.patch("/{task_id}", response_model=TaskOut)
@limiter.limit("30/minute")
async def update_task(
    request: Request,
    task_id: int,
    task_update: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Task).where(Task.id == task_id)
    
    if current_user.role == UserRole.super_admin:
        pass
    elif current_user.role == UserRole.tenant_admin:
        stmt = stmt.where(Task.tenant_id == current_user.tenant_id)
    else:
        stmt = stmt.where(
            Task.tenant_id == current_user.tenant_id,
            Task.user_id == current_user.id
        )
        
    result = await db.execute(stmt)
    task = result.scalars().first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or you do not have permission to update it")
        
    update_data = task_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)
        
    if task_update.status == TaskStatus.completed and not task.completed_at:
        task.completed_at = datetime.now()
        
    await db.commit()
    await db.refresh(task)

    # ✅ Invalidate all task caches
    await invalidate_task_cache(task.tenant_id)
    
    # ✅ Log the update action
    await ActivityLogService.log(
        db=db, tenant_id=task.tenant_id, user_id=current_user.id,
        action="update_task", target_type="task", target_id=task.id,
        details={"task_title": task.title, "changed_fields": list(update_data.keys())}
    )
    await db.commit()  # Commit the activity log flush

    return task
