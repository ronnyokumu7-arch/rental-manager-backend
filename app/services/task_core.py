# app/services/task_core.py

from datetime import datetime
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
    ):
        """
        UNIVERSAL ROUTER:
        1. Duplicate Check (Only for system-generated tasks to prevent spam).
        2. Plan A: Direct Assignment (if assignee_id provided).
        3. Plan B: Role Matching (if target_role provided).
        4. Plan C: Unassigned Pool (fallback).
        """
        
        # 1. Duplicate Check (Prevents auto-task spam)
        if is_system_generated:
            existing_stmt = select(Task).where(
                Task.tenant_id == tenant_id,
                Task.target_type == target_type,
                Task.target_id == target_id,
                Task.title == title,
                Task.status != TaskStatus.completed
            )
            existing_result = await db.execute(existing_stmt)
            existing = existing_result.scalars().first()
            
            if existing:
                return  # Task already exists, do nothing.

        # 2. Determine Assignment Strategy
        final_user_id = assignee_id
        final_status = TaskStatus.pending if assignee_id else TaskStatus.unassigned
        final_requires_role = None

        # Plan B: Role Matching (Only if no direct assignee is provided)
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
                # Plan C: Fallback to Unassigned Pool
                final_requires_role = target_role

        # 3. Create the Task
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
            is_system_generated=is_system_generated, 
            target_type=target_type, 
            target_id=target_id
        )
        
        db.add(task)
        await db.commit()
        await db.refresh(task) # Refresh to get the ID
        return task
