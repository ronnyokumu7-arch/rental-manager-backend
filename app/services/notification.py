import logging
from datetime import datetime, timedelta, timezone
from typing import List, Union

from sqlalchemy import select, func, update, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.notifications import Notification, NotificationType, NotificationPriority
from app.schemas.notification import NotificationCountResponse

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Handles all notification logic: creation, retrieval, and state management.
    """

    # ─── CACHE HELPERS ─────────────────────────────────────────────────────
    @staticmethod
    async def _invalidate_user_cache(user_id: int) -> None:
        """
        Clears Redis cache for a specific user's notification counts.
        ✅ FIX: Uses SCAN to match the actual keys written by the cache service.
        """
        try:
            from app.core.redis_client import get_redis
            redis = await get_redis()
            if redis:
                # Match the keys written by app/services/cache/notification.py
                pattern = f"notifications:*user_{user_id}*"
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        await redis.delete(*keys)
                    if cursor == 0:
                        break
        except Exception as e:
            # ✅ FIX: Use logger.exception instead of print/logger.warning
            logger.exception(f"Failed to invalidate notification cache for user {user_id}")

    # ─── CREATION ──────────────────────────────────────────────────────────
    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        tenant_id: int,
        user_ids: Union[int, List[int]],
        type: NotificationType,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.normal,
        payload: dict = None,
        action_url: str = None,
    ) -> List[Notification]:
        """
        Creates notifications for one or more users.
        Uses flush() to get IDs. Caller MUST commit the transaction.
        """
        if isinstance(user_ids, int):
            user_ids = [user_ids]

        notifications = []
        for uid in user_ids:
            notif = Notification(
                tenant_id=tenant_id,
                user_id=uid,
                type=type,
                priority=priority,
                title=title,
                message=message,
                payload=payload or {},
                action_url=action_url,
                is_read=False,
            )
            db.add(notif)
            notifications.append(notif)

        await db.flush()  # Get IDs before commit
        
        # Invalidate cache for all affected users
        for uid in user_ids:
            await cls._invalidate_user_cache(uid)

        return notifications

    # ─── RETRIEVAL ─────────────────────────────────────────────────────────
    @classmethod
    async def get_list(
        cls,
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        per_page: int = 20,
        filter: str = "all",  # ✅ UPDATED: Replaced unread_only with filter ("all", "unread", "read")
    ) -> dict:
        """Fetches paginated notifications for a user with filtering."""
        stmt = select(Notification).where(Notification.user_id == user_id)
        count_stmt = select(func.count(Notification.id)).where(Notification.user_id == user_id)

        if filter == "unread":
            stmt = stmt.where(Notification.is_read == False)
            count_stmt = count_stmt.where(Notification.is_read == False)
        elif filter == "read":
            stmt = stmt.where(Notification.is_read == True)
            count_stmt = count_stmt.where(Notification.is_read == True)

        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(desc(Notification.created_at))
        
        offset = (page - 1) * per_page
        stmt = stmt.offset(offset).limit(per_page)

        result = await db.execute(stmt)
        items = result.scalars().all()

        has_more = (page * per_page) < total

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "has_more": has_more,
        }

    @classmethod
    async def get_counts(cls, db: AsyncSession, user_id: int) -> NotificationCountResponse:
        """Gets unread and total counts."""
        unread_stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False
        )
        total_stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id
        )

        unread_count = (await db.execute(unread_stmt)).scalar() or 0
        total_count = (await db.execute(total_stmt)).scalar() or 0

        return NotificationCountResponse(
            unread_count=unread_count,
            total_count=total_count
        )

    # ─── STATE MANAGEMENT ──────────────────────────────────────────────────
    @classmethod
    async def mark_as_read(cls, db: AsyncSession, user_id: int, notification_id: int) -> Notification:
        """Marks a specific notification as read."""
        stmt = (
            select(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .with_for_update()
        )
        result = await db.execute(stmt)
        notif = result.scalars().first()

        if not notif:
            raise NotFoundError(message="Notification not found.")

        if not notif.is_read:
            notif.is_read = True
            await db.flush()
            await db.commit()  # ✅ FIX: Added commit to persist the change
            await cls._invalidate_user_cache(user_id)

        return notif

    @classmethod
    async def mark_all_as_read(cls, db: AsyncSession, user_id: int) -> int:
        """Marks all unread notifications for a user as read."""
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)
            .values(is_read=True)
        )
        result = await db.execute(stmt)
        await db.flush()
        await db.commit()  # ✅ FIX: Added commit to persist the change
        
        if result.rowcount > 0:
            await cls._invalidate_user_cache(user_id)
            
        return result.rowcount

    # ─── BULK ACTIONS (Added for Multi-Select UI) ──────────────────────────
    @classmethod
    async def mark_multiple_as_read(cls, db: AsyncSession, user_id: int, notification_ids: List[int]) -> int:
        """Marks specific notifications as read for the current user."""
        if not notification_ids:
            return 0
            
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id, 
                Notification.id.in_(notification_ids),
                Notification.is_read == False
            )
            .values(is_read=True)
        )
        result = await db.execute(stmt)
        await db.flush()
        await db.commit()  # ✅ FIX: Added commit to persist the change
        
        if result.rowcount > 0:
            await cls._invalidate_user_cache(user_id)
            
        return result.rowcount

    @classmethod
    async def delete_multiple(cls, db: AsyncSession, user_id: int, notification_ids: List[int]) -> int:
        """Hard deletes specific notifications for the current user (used for 'Archive')."""
        if not notification_ids:
            return 0

        stmt = delete(Notification).where(
            Notification.user_id == user_id,
            Notification.id.in_(notification_ids)
        )
        result = await db.execute(stmt)
        await db.flush()
        await db.commit()  # ✅ FIX: Added commit to persist the change
        
        if result.rowcount > 0:
            await cls._invalidate_user_cache(user_id)
            
        return result.rowcount

    # ─── CLEANUP & ARCHIVING ───────────────────────────────────────────────
    @classmethod
    async def clear_read_notifications(cls, db: AsyncSession, user_id: int) -> int:
        """Manually clears all read notifications for a specific user."""
        stmt = delete(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read == True
        )
        result = await db.execute(stmt)
        await db.flush()
        await db.commit()  # ✅ FIX: Reverted to commit() to ensure deletion persists
        
        if result.rowcount > 0:
            await cls._invalidate_user_cache(user_id)
            
        return result.rowcount

    @classmethod
    async def archive_old_read_notifications(cls, db: AsyncSession, days_to_keep: int = 30) -> int:
        """Background job helper: Hard deletes read notifications older than X days."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        
        stmt = delete(Notification).where(
            Notification.is_read == True,
            Notification.created_at < cutoff_date
        )
        result = await db.execute(stmt)
        await db.flush()
        await db.commit()  # ✅ FIX: Reverted to commit() to ensure deletion persists
        
        return result.rowcount
