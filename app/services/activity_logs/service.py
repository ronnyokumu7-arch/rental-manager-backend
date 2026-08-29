import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.services.cache import invalidate_activity_log_cache

logger = logging.getLogger(__name__)


class ActivityLogService:
    """Centralized service for recording audit trail events."""

    @staticmethod
    async def log(
        db: AsyncSession,
        tenant_id: int,
        user_id: Optional[int],  # ✅ system/scheduler events have no actor (NULL)
        action: str,
        label: str = "Activity",
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        summary: Optional[dict[str, Any]] = None,
        details: Optional[dict[str, Any]] = None,
        priority: int = 2,
    ) -> Optional[ActivityLog]:
        """
        Record an activity log row.

        ✅ FLUSH-ONLY by design: the caller owns the transaction and commits.
        ⚠️ Callers that invoke loggers AFTER their main commit MUST commit
           again afterwards, or the rows roll back on session close.

        ✅ SAVEPOINT isolation: a logging failure can never poison the
           outer business transaction (no PendingRollbackError leaks).
        """
        log_entry: Optional[ActivityLog] = None
        try:
            async with db.begin_nested():  # SAVEPOINT
                log_entry = ActivityLog(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=action,
                    label=label,
                    target_type=target_type,
                    target_id=target_id,
                    summary=summary,
                    details=details,
                    priority=priority,
                )
                db.add(log_entry)
                await db.flush()  # assigns ID without committing
        except Exception as e:
            logger.error(f"Failed to record activity log: {e}", exc_info=True)
            return None

        # ✅ Best-effort cache invalidation — can't kill a successful write
        try:
            await invalidate_activity_log_cache(tenant_id, user_id)
        except Exception as e:
            logger.warning(f"Activity-log cache invalidation failed: {e}")

        return log_entry

    @staticmethod
    async def log_safe(
        db: AsyncSession,
        tenant_id: int,
        user_id: Optional[int],
        action: str,
        label: str = "Activity",
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        summary: Optional[dict[str, Any]] = None,
        details: Optional[dict[str, Any]] = None,
        priority: int = 2,
    ) -> None:
        """✅ Fire-and-forget logging (does NOT raise errors)."""
        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            label=label,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            details=details,
            priority=priority,
        )
