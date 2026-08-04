from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskOut
from app.services.cache import invalidate_task_cache
from app.services.activity_log import ActivityLogService

router = APIRouter()

admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))


@router.post("/", response_model=TaskOut)
@limiter.limit("30/minute")
async def create_task(
    request: Request,
    task: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Permission Check
    if task.user_id and task.user_id != current_user.id and current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        raise HTTPException(status_code=403, detail="Only admins can assign tasks to others")
        
    # 2. ✅ SECURITY FIX: Validate that assignee belongs to the current tenant
    if task.user_id:
        user_check_stmt = select(User).where(
            User.id == task.user_id,
            User.tenant_id == current_user.tenant_id
        )
        user_check_result = await db.execute(user_check_stmt)
        if not user_check_result.scalars().first():
            raise HTTPException(status_code=400, detail="Cannot assign task to a user outside your tenant")

    task_data = task.model_dump(exclude={"is_system_generated", "created_by"})
    
    db_task = Task(
        **task_data,
        tenant_id=current_user.tenant_id,
        is_system_generated=False,  # Manual tasks are never system generated
        created_by=current_user.id
    )
    
    if not db_task.user_id:
        db_task.status = TaskStatus.unassigned
        
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)

    # ✅ Invalidate all task caches to ensure the new task appears in feeds/pools
    await invalidate_task_cache(db_task.tenant_id)
    
    # ✅ Log the creation action
    await ActivityLogService.log(
        db=db, tenant_id=db_task.tenant_id, user_id=current_user.id,
        action="create_task", target_type="task", target_id=db_task.id,
        details={"task_title": db_task.title, "assigned_to_user_id": db_task.user_id}
    )
    await db.commit()  # Commit the activity log flush

    return db_task


@router.delete("/{task_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_task(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalars().first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # Permission Check
    if current_user.role not in [UserRole.tenant_admin, UserRole.super_admin]:
        if task.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this task")
            
    # ✅ ARCHITECTURE FIX: Soft Delete (Archive) instead of Hard Delete
    # This preserves the audit trail for system-generated tasks and completed work.
    task.is_archived = True
    await db.commit()

    # ✅ Invalidate all task caches
    await invalidate_task_cache(task.tenant_id)
    
    # ✅ Log the archival action
    await ActivityLogService.log(
        db=db, tenant_id=task.tenant_id, user_id=current_user.id,
        action="archive_task", target_type="task", target_id=task.id,
        details={"task_title": task.title}
    )
    await db.commit()  # Commit the activity log flush
