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
        user_id: int,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> Optional[ActivityLog]:
        try:
            log_entry = ActivityLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
            db.add(log_entry)
            await db.flush()  # Flush to get ID without committing
            
            await invalidate_activity_log_cache(tenant_id, user_id)
            return log_entry
        except Exception as e:
            logger.error(f"Failed to record activity log: {e}", exc_info=True)
            return None

    @staticmethod
    async def log_safe(
        db: AsyncSession,
        tenant_id: int,
        user_id: int,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        await ActivityLogService.log(
            db=db, tenant_id=tenant_id, user_id=user_id, action=action,
            target_type=target_type, target_id=target_id, details=details,
        )
