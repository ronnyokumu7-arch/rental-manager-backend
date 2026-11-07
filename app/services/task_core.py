# app/services/task_core.py

from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus, TaskPriority
from app.models.users import User


class TaskCoreService:
    """
    Universal Task Engine (Tier 1 Auto-Tasks & Future Manual Tasks)
    Supports direct assignment, role-based routing, and unassigned pools.
    """

    @staticmethod
    async def smart_create_task(
        db: AsyncSession, 
        tenant_id: int,
        title: str, 
        description: str, 
        category: str, 
        priority: TaskPriority, 
        due_date: datetime,
        target_type: str, 
        target_id: int,
        target_role: str = None,       # Optional: For auto-assignment by job title
        assignee_id: int = None,       # Optional: For direct assignment (manual tasks)
        is_system_generated: bool = True
    ) -> Optional[Task]:
        """
        System-generated tasks are disabled; manually requested tasks remain
        available through the existing task-management flow.
        """
        if is_system_generated:
            return None

        final_user_id = assignee_id
        final_status = TaskStatus.pending if assignee_id else TaskStatus.unassigned
        final_requires_role = None

        if not final_user_id and target_role:
            assignee_stmt = select(User).where(
                User.job_title == target_role,
                User.tenant_id == tenant_id,
                User.is_active == True
            )
            assignee_result = await db.execute(assignee_stmt)
            role_match = assignee_result.scalars().first()

            if role_match:
                final_user_id = role_match.id
                final_status = TaskStatus.pending
            else:
                final_requires_role = target_role

        task = Task(
            tenant_id=tenant_id,
            user_id=final_user_id,
            requires_role=final_requires_role,
            title=title,
            description=description,
            category=category,
            priority=priority,
            due_date=due_date,
            status=final_status,
            is_system_generated=False,
            target_type=target_type,
            target_id=target_id
        )

        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task
