# app/routers/vault/tasks.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.task import Task, TaskStatus
from app.models.users import User
from app.schemas.pagination import PaginatedResponse, paginate_items
from app.schemas.task import TaskOut
from app.services.cache import invalidate_task_cache
from app.services.activity_log import ActivityLogService

router = APIRouter(prefix="/tasks", tags=["vault-tasks"])

@router.get("/", response_model=PaginatedResponse[TaskOut])
@limiter.limit("60/minute")
async def list_vault_tasks(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch tasks that are either explicitly archived OR completed
    stmt = select(Task).where(
        Task.tenant_id == current_user.tenant_id,
        or_(
            Task.is_archived == True,
            Task.status == TaskStatus.completed
        )
    )
    
    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(Task.title.ilike(search_lower))
        
    # Sort by completion date first, then by last update
    stmt = stmt.order_by(
        Task.completed_at.desc().nullslast(), 
        Task.updated_at.desc()
    )
    
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return paginate_items(tasks, total=len(tasks), page=page, page_size=page_size)

@router.post("/{task_id}/restore", response_model=TaskOut)
@limiter.limit("10/minute")
async def restore_vault_task(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Task).where(
        Task.id == task_id,
        Task.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found in vault")
        
    # Restore logic: Flip the archive flag
    task.is_archived = False
    
    # If it was completed, bring it back to the active feed as 'pending'
    if task.status == TaskStatus.completed:
        task.status = TaskStatus.pending
        task.completed_at = None
        
    await db.commit()
    await db.refresh(task)

    # ✅ Invalidate all task caches so the restored task appears in the active feed
    await invalidate_task_cache(task.tenant_id)
    
    # ✅ Log the restore action
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="restore_task", target_type="task", target_id=task.id,
        details={"task_title": task.title}
    )
    await db.commit()  # Commit the activity log flush

    return task

@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def hard_delete_vault_task(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Task).where(
        Task.id == task_id,
        Task.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    task = result.scalars().first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found in vault")
        
    # Capture details before permanent deletion
    task_title = task.title
        
    # Hard delete: Permanent destruction from the database
    await db.delete(task)
    await db.commit()

    # ✅ Invalidate all task caches
    await invalidate_task_cache(task.tenant_id)
    
    # ✅ Log the hard delete action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        action="hard_delete_task", target_type="task", target_id=task_id,
        details={"task_title": task_title}
    )
    await db.commit()  # Commit the activity log flush
