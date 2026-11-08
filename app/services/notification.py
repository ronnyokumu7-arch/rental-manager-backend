import logging
from datetime import datetime, timedelta, timezone
from typing import List, Union

from fastapi_cache.decorator import cache
from sqlalchemy import select, func, update, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.notifications import Notification, NotificationType, NotificationPriority
from app.schemas.notification import NotificationCreate, NotificationOut, NotificationCountResponse

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Handles all notification logic: creation, retrieval, and state management.
    Integrates with Redis to cache unread counts for high-performance UI updates.
    """

    # ─── CACHE HELPERS ─────────────────────────────────────────────────────
    @staticmethod
    async def _invalidate_user_cache(user_id: int) -> None:
        """Clears Redis cache for a specific user's notification counts."""
        try:
            from app.core.redis_client import get_redis
            redis = await get_redis()
            if redis:
                # Delete both unread and total count keys
                await redis.delete(f"notification:unread:{user_id}")
                await redis.delete(f"notification:total:{user_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate notification cache for user {user_id}: {e}")

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
        metadata: dict = None,
        action_url: str = None,
    ) -> List[Notification]:
        """
        Creates notifications for one or more users.
        Automatically invalidates their unread count cache.
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
                metadata=metadata or {},
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
        unread_only: bool = False,
    ) -> dict:
        """
        Fetches paginated notifications for a user.
        """
        # Base query
        stmt = select(Notification).where(Notification.user_id == user_id)
        count_stmt = select(func.count(Notification.id)).where(Notification.user_id == user_id)

        if unread_only:
            stmt = stmt.where(Notification.is_read == False)
            count_stmt = count_stmt.where(Notification.is_read == False)

        # Get total count
        total = (await db.execute(count_stmt)).scalar() or 0

        # Order by newest first
        stmt = stmt.order_by(desc(Notification.created_at))
        
        # Pagination
        offset = (page - 1) * per_page
        stmt = stmt.offset(offset).limit(per_page)

        # Execute
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
        """
        Gets unread and total counts. 
        Note: In a production setup, you might wrap this with @cache(expire=60) 
        from fastapi_cache, but since we invalidate on write, we can also just query DB 
        or use a manual Redis get/set here. For simplicity and consistency with your 
        existing cache setup, we'll query the DB directly (it's fast with the index).
        """
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
            await cls._invalidate_user_cache(user_id)

        return notif

    @classmethod
    async def mark_all_as_read(cls, db: AsyncSession, user_id: int) -> int:
        """Marks all unread notifications for a user as read. Returns count of updated rows."""
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)
            .values(is_read=True)
        )
        result = await db.execute(stmt)
        await db.flush()
        
        if result.rowcount > 0:
            await cls._invalidate_user_cache(user_id)
            
        return result.rowcount

    # ─── CLEANUP & ARCHIVING ───────────────────────────────────────────────
    @classmethod
    async def clear_read_notifications(cls, db: AsyncSession, user_id: int) -> int:
        """
        Manually clears all read notifications for a specific user.
        Used by the "Clear read" button in the UI.
        """
        stmt = delete(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read == True
        )
        result = await db.execute(stmt)
        await db.commit()
        
        if result.rowcount > 0:
            await cls._invalidate_user_cache(user_id)
            
        return result.rowcount

    @classmethod
    async def archive_old_read_notifications(cls, db: AsyncSession, days_to_keep: int = 30) -> int:
        """
        Background job helper: Hard deletes read notifications older than X days 
        to keep the database table small and performant.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        
        stmt = delete(Notification).where(
            Notification.is_read == True,
            Notification.created_at < cutoff_date
        )
        result = await db.execute(stmt)
        await db.commit()
        
        return result.rowcount
