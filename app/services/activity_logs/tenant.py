# app/services/activity_logs/tenant.py

from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService


class TenantActivityLogger:
    """Activity logging helpers for tenant (Agency) lifecycle events."""

    @staticmethod
    async def on_created(db: AsyncSession, user_id: int, tenant) -> None:
        """Log a new tenant (Agency) creation event."""
        summary = {
            "tenant_name": tenant.name,
            "admin_email": tenant.admin_email,
            "plan": tenant.plan,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant.id,
            user_id=user_id,
            action="create_tenant",
            label="New Agency Created",
            target_type="tenant",
            target_id=tenant.id,
            summary=summary,
            details={
                "tenant_name": tenant.name,
                "admin_email": tenant.admin_email,
                "plan": tenant.plan,
            },
            priority=3,  # High (New Revenue)
        )

    @staticmethod
    async def on_updated(db: AsyncSession, user_id: int, tenant, changed_fields: list[str]) -> None:
        """Log a tenant profile update event."""
        summary = {
            "tenant_name": tenant.name,
            "changed_fields": changed_fields,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant.id,
            user_id=user_id,
            action="update_tenant",
            label="Agency Updated",
            target_type="tenant",
            target_id=tenant.id,
            summary=summary,
            details={
                "tenant_name": tenant.name,
                "changed_fields": changed_fields,
            },
            priority=2,  # Normal
        )

    @staticmethod
    async def on_suspended(db: AsyncSession, user_id: int, tenant, reason: str) -> None:
        """Log a tenant suspension event."""
        summary = {
            "tenant_name": tenant.name,
            "reason": reason,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant.id,
            user_id=user_id,
            action="suspend_tenant",
            label="Agency Suspended",
            target_type="tenant",
            target_id=tenant.id,
            summary=summary,
            details={
                "tenant_name": tenant.name,
                "reason": reason,
            },
            priority=4,  # Critical (Account Blocked)
        )

    @staticmethod
    async def on_activated(db: AsyncSession, user_id: int, tenant) -> None:
        """Log a tenant activation event."""
        summary = {
            "tenant_name": tenant.name,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant.id,
            user_id=user_id,
            action="activate_tenant",
            label="Agency Activated",
            target_type="tenant",
            target_id=tenant.id,
            summary=summary,
            details={
                "tenant_name": tenant.name,
            },
            priority=3,  # High (Revenue Restored)
        )

    @staticmethod
    async def on_archived(db: AsyncSession, user_id: int, tenant) -> None:
        """Log a tenant archive event."""
        summary = {
            "tenant_name": tenant.name,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant.id,
            user_id=user_id,
            action="archive_tenant",
            label="Agency Archived",
            target_type="tenant",
            target_id=tenant.id,
            summary=summary,
            details={
                "tenant_name": tenant.name,
            },
            priority=3,  # High (Revenue Loss)
        )

    @staticmethod
    async def on_deleted(db: AsyncSession, user_id: int, tenant_id: int, tenant_name: str, hard_delete: bool) -> None:
        """Log a tenant deletion event."""
        summary = {
            "tenant_name": tenant_name,
            "hard_delete": hard_delete,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="delete_tenant",
            label="Agency Deleted",
            target_type="tenant",
            target_id=tenant_id,
            summary=summary,
            details={
                "tenant_name": tenant_name,
                "hard_delete": hard_delete,
            },
            priority=4,  # Critical (Data Loss)
        )
