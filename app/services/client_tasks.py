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
        """Triggered when a new client is added. Checks for pending verification and missing docs."""
        
        # 1. Verification Task (If client is in 'pending' status)
        if client.status == ClientStatus.pending:
            await TaskCoreService.smart_create_task(
                db=db, tenant_id=tenant_id, target_role="HR",
                title=f"Verify New Client: {client.full_name}",
                description=f"New client registered. Review submitted details and approve or reject the account.",
                category="hr", priority=TaskPriority.medium,
                due_date=datetime.now() + timedelta(hours=24),
                target_type="client", target_id=client.id
            )

        # 2. Missing Documents Check
        missing_docs = []
        if not client.id_number: missing_docs.append("National ID Number")
        if not client.dl_number: missing_docs.append("Driver's License Number")
        if not client.id_image_front: missing_docs.append("ID Photo")
        if not client.dl_image_front: missing_docs.append("DL Photo")

        if missing_docs:
            missing_list = ", ".join(missing_docs)
            await TaskCoreService.smart_create_task(
                db=db, tenant_id=tenant_id, target_role="HR",
                title=f"Request Missing Docs for {client.full_name}",
                description=f"Client profile is incomplete. Please request the following from the client: {missing_list}.",
                category="compliance", priority=TaskPriority.high,
                due_date=datetime.now() + timedelta(hours=12),
                target_type="client", target_id=client.id
            )
