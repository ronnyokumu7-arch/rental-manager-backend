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
        label: str = "Activity",  # ✅ NEW: Human-readable label for UI
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        summary: Optional[dict[str, Any]] = None,  # ✅ NEW: Denormalized snapshot
        details: Optional[dict[str, Any]] = None,
        priority: int = 2,  # ✅ NEW: Priority for dashboard alerts
    ) -> Optional[ActivityLog]:
        """
        ✅ Centralized logging with new fields.

        - `label`: Human-readable title (e.g., "Payment Received", "Trip Overdue")
        - `summary`: Denormalized data snapshot for instant UI rendering (prevents MissingGreenlet)
        - `priority`: Criticality level (1=Low, 2=Normal, 3=High, 4=Critical)
        """
        try:
            log_entry = ActivityLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                label=label,  # ✅ NEW
                target_type=target_type,
                target_id=target_id,
                summary=summary,  # ✅ NEW
                details=details,
                priority=priority,  # ✅ NEW
            )
            db.add(log_entry)
            await db.flush()  # Flush to get ID without committing
            
            # ✅ Invalidate cache for ALL filter variations (Today/Week/Month)
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
        label: str = "Activity",  # ✅ NEW
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        summary: Optional[dict[str, Any]] = None,  # ✅ NEW
        details: Optional[dict[str, Any]] = None,
        priority: int = 2,  # ✅ NEW
    ) -> None:
        """
        ✅ Fire-and-forget logging (does NOT raise errors).
        """
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
