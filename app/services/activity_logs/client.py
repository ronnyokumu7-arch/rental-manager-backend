from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService


class ClientActivityLogger:
    """Logger for Client lifecycle events."""

    @staticmethod
    async def on_created(db: AsyncSession, tenant_id: int, user_id: int, client) -> None:
        """
        Log a client creation event.
        
        ✅ SNAPSHOT PATTERN: Builds a summary with client's name and phone 
        to prevent MissingGreenlet errors in the UI.
        """
        summary = {
            "client_name": client.full_name,
            "client_phone": client.phone,
            "email": client.email,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="create_client",
            label="New Client Added",
            target_type="client",
            target_id=client.id,
            summary=summary,
            details={
                "client_name": client.full_name,
                "phone": client.phone,
                "email": client.email,
            },
            priority=2,  # Normal
        )

    @staticmethod
    async def on_status_changed(db: AsyncSession, tenant_id: int, user_id: int, client, old_status: str, new_status: str) -> None:
        """
        Log a client status change (Active, Suspended, Inactive, Pending).
        """
        # ✅ Suspended is High Priority (Potential issue for bookings)
        priority = 2
        if new_status == "suspended":
            priority = 3

        summary = {
            "client_name": client.full_name,
            "client_phone": client.phone,
            "old_status": old_status,
            "new_status": new_status,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="update_client_status",
            label=f"Client {new_status.replace('_', ' ').title()}",
            target_type="client",
            target_id=client.id,
            summary=summary,
            details={
                "client_name": client.full_name,
                "old_status": old_status,
                "new_status": new_status,
            },
            priority=priority,
        )

    @staticmethod
    async def on_archived(db: AsyncSession, tenant_id: int, user_id: int, client) -> None:
        """
        Log a client archive event.
        """
        summary = {
            "client_name": client.full_name,
            "client_phone": client.phone,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="archive_client",
            label="Client Archived",
            target_type="client",
            target_id=client.id,
            summary=summary,
            details={
                "client_name": client.full_name,
            },
            priority=2,  # Normal
        )
