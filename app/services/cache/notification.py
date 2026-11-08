import json
import logging
from typing import Optional, List

from app.core.redis_client import get_redis
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item

logger = logging.getLogger(__name__)

# Shorter TTL for notifications since they're user-facing and need to feel real-time
NOTIFICATION_COUNT_TTL = 60  # 1 minute for counts (badge)
NOTIFICATION_LIST_TTL = 120  # 2 minutes for list (dropdown)


def _build_cache_key(
    tenant_id: int,
    user_id: int,
    key_type: str,  # "count" or "list"
    page: int = 1,
    per_page: int = 20,
    unread_only: bool = False,
) -> str:
    """
    Build a deterministic cache key for notification data.
    Ensures different filters get different cache entries.
    """
    parts = [
        f"tenant_{tenant_id}",
        f"user_{user_id}",
        f"type_{key_type}",
        f"page_{page}",
        f"per_page_{per_page}",
        f"unread_{unread_only}",
    ]
    return f"notifications:{':'.join(parts)}"


async def get_cached_notification_counts(
    tenant_id: int,
    user_id: int,
) -> Optional[dict]:
    """
    Retrieve cached unread/total counts for the notification badge.
    Returns serialized JSON dict or None if cache miss/unavailable.
    """
    redis = await get_redis()
    if not redis:
        return None

    try:
        cache_key = _build_cache_key(tenant_id, user_id, "count")
        cached = await redis.get(cache_key)
        
        if cached:
            return json.loads(cached)
        return None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read notification count cache: {e}")
        return None


async def set_cached_notification_counts(
    tenant_id: int,
    user_id: int,
    unread_count: int,
    total_count: int,
) -> None:
    """
    Store notification counts in cache.
    Uses short TTL to keep badge feeling fresh without hammering DB.
    """
    redis = await get_redis()
    if not redis:
        return

    try:
        cache_key = _build_cache_key(tenant_id, user_id, "count")
        data = {
            "unread_count": unread_count,
            "total_count": total_count,
        }
        await redis.setex(
            cache_key,
            NOTIFICATION_COUNT_TTL,
            json.dumps(data)
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to write notification count cache: {e}")


async def get_cached_notification_list(
    tenant_id: int,
    user_id: int,
    page: int = 1,
    per_page: int = 20,
    unread_only: bool = False,
) -> Optional[List[dict]]:
    """
    Retrieve cached notification list for the dropdown.
    Returns serialized list of notification dicts or None.
    """
    redis = await get_redis()
    if not redis:
        return None

    try:
        cache_key = _build_cache_key(
            tenant_id, user_id, "list", page, per_page, unread_only
        )
        cached = await redis.get(cache_key)
        return deserialize_cache_list(cached) if cached else None
    except Exception as e:
        logger.warning(f"️ Failed to read notification list cache: {e}")
        return None


async def set_cached_notification_list(
    tenant_id: int,
    user_id: int,
    notifications: Optional[List],
    page: int = 1,
    per_page: int = 20,
    unread_only: bool = False,
) -> None:
    """
    Store serialized notification list in cache.
    Accepts either Pydantic models or ORM objects and serializes safely.
    """
    redis = await get_redis()
    if not redis:
        return

    try:
        cache_key = _build_cache_key(
            tenant_id, user_id, "list", page, per_page, unread_only
        )

        # Serialize safely (strip ORM relationships)
        data = []
        if notifications:
            for notif in notifications:
                if hasattr(notif, 'model_dump'):
                    # Pydantic v2
                    try:
                        data.append(notif.model_dump(mode="json"))
                    except TypeError:
                        data.append(notif.model_dump())
                elif hasattr(notif, 'dict'):
                    # Pydantic v1
                    data.append(notif.dict())
                else:
                    # ORM object: manually extract fields
                    data.append({
                        "id": notif.id,
                        "tenant_id": notif.tenant_id,
                        "user_id": notif.user_id,
                        "type": notif.type.value if hasattr(notif.type, 'value') else notif.type,
                        "priority": notif.priority.value if hasattr(notif.priority, 'value') else notif.priority,
                        "title": notif.title,
                        "message": notif.message,
                        "metadata": notif.metadata or {},
                        "action_url": notif.action_url,
                        "is_read": notif.is_read,
                        "created_at": notif.created_at.isoformat() if notif.created_at else None,
                        "updated_at": notif.updated_at.isoformat() if notif.updated_at else None,
                    })

        await redis.setex(
            cache_key,
            NOTIFICATION_LIST_TTL,
            json.dumps(serialize_cache_item(data))
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to write notification list cache: {e}")


async def invalidate_notification_cache(
    tenant_id: int,
    user_id: Optional[int] = None,
) -> None:
    """
    Invalidate notification cache keys.
    
    If user_id is provided, only invalidates that user's keys.
    If user_id is None, invalidates ALL notification keys for the tenant
    (useful for admin operations or bulk notifications).
    """
    redis = await get_redis()
    if not redis:
        return

    try:
        if user_id:
            pattern = f"notifications:*user_{user_id}*"
        else:
            pattern = f"notifications:*tenant_{tenant_id}*"

        cursor = 0
        deleted_count = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                deleted_count += len(keys)
            if cursor == 0:
                break
        
        if deleted_count > 0:
            logger.info(f"✅ Invalidated {deleted_count} notification cache keys for tenant {tenant_id}")
    except Exception as e:
        logger.warning(f"️ Failed to invalidate notification cache: {e}")


async def invalidate_user_notification_cache(user_id: int) -> None:
    """
    Convenience wrapper to invalidate cache for a specific user.
    Use this after creating, reading, or marking notifications as read.
    """
    # We don't have tenant_id here, so we invalidate by user_id pattern only
    redis = await get_redis()
    if not redis:
        return

    try:
        pattern = f"notifications:*user_{user_id}*"
        
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate user notification cache: {e}")
