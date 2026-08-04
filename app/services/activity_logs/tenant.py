from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class TenantActivityLogger:
    @staticmethod
    async def on_created(db: AsyncSession, user_id: int, tenant) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant.id, user_id=user_id, action="create_tenant", target_type="tenant", target_id=tenant.id, details={"tenant_name": tenant.name, "admin_email": tenant.admin_email, "plan": tenant.plan})

    @staticmethod
    async def on_updated(db: AsyncSession, user_id: int, tenant, changed_fields: list[str]) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant.id, user_id=user_id, action="update_tenant", target_type="tenant", target_id=tenant.id, details={"tenant_name": tenant.name, "changed_fields": changed_fields})

    @staticmethod
    async def on_suspended(db: AsyncSession, user_id: int, tenant, reason: str) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant.id, user_id=user_id, action="suspend_tenant", target_type="tenant", target_id=tenant.id, details={"tenant_name": tenant.name, "reason": reason})

    @staticmethod
    async def on_activated(db: AsyncSession, user_id: int, tenant) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant.id, user_id=user_id, action="activate_tenant", target_type="tenant", target_id=tenant.id, details={"tenant_name": tenant.name})

    @staticmethod
    async def on_archived(db: AsyncSession, user_id: int, tenant) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant.id, user_id=user_id, action="archive_tenant", target_type="tenant", target_id=tenant.id, details={"tenant_name": tenant.name})

    @staticmethod
    async def on_deleted(db: AsyncSession, user_id: int, tenant_id: int, tenant_name: str, hard_delete: bool) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="delete_tenant", target_type="tenant", target_id=tenant_id, details={"tenant_name": tenant_name, "hard_delete": hard_delete})
