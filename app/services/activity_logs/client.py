from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class ClientActivityLogger:
    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: int, client) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="create_client", target_type="client", target_id=client.id, details={"client_name": client.full_name, "phone": client.phone})

    @staticmethod
    async def on_status_changed(db: AsyncSession, tenant_id: int, user_id: int, client, old_status: str, new_status: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="update_client_status", target_type="client", target_id=client.id, details={"client_name": client.full_name, "old_status": old_status, "new_status": new_status})

    @staticmethod
    async def on_archived(db: AsyncSession, tenant_id: int, user_id: int, client) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="archive_client", target_type="client", target_id=client.id, details={"client_name": client.full_name})
