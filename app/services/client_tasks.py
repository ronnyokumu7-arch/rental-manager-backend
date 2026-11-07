# app/services/client_task_service.py

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client, ClientStatus
from app.models.task import TaskPriority
from app.services.task_core import TaskCoreService


class ClientTaskService:
    """Handles all task generation logic specific to the Client lifecycle."""

    @staticmethod
    async def on_client_created(db: AsyncSession, client: Client, tenant_id: int):
        """Triggered when a new client is added.

        Intake deliberately contains no documents or driving selection, so the
        only useful follow-up at this point is to start verification. Missing
        document tasks are created only after a verification attempt, not for
        every newly-created account.
        """
        
        # 1. Verification Task (If client is in 'pending' status)
        if client.status == ClientStatus.pending:
            await TaskCoreService.smart_create_task(
                db=db, tenant_id=tenant_id, target_role="HR",
                title=f"Verify New Client: {client.full_name}",
                description=f"New client registered. Send the verification link when ready.",
                category="hr", priority=TaskPriority.medium,
                due_date=datetime.now() + timedelta(hours=24),
                target_type="client", target_id=client.id
            )
