import json
import logging
from typing import Optional, Any, List
from datetime import datetime, date
from decimal import Decimal

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 300


def _serialize_obj(obj: Any) -> Any:
    """Convert Pydantic models, datetime, and Decimal to JSON-safe types."""
    if hasattr(obj, "model_dump"):
        try:
            # Pydantic v2 handles datetime/Decimal natively with mode="json"
            return obj.model_dump(mode="json")
        except TypeError:
            # Fallback for Pydantic v1
            return obj.dict()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    return obj


async def get_cached_client_list(
    tenant_id: Optional[int],
    archived: bool = False
) -> Optional[List[dict]]:
    redis = await get_redis()
    if not redis:
        return None

    try:
        cached = await redis.get(f"clients:tenant_{tenant_id}:archived_{archived}")
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.warning(f"⚠️ Failed to read client cache: {e}")
        return None


async def set_cached_client_list(
    tenant_id: Optional[int],
    archived: bool = False,
    clients: Optional[List[Any]] = None
) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        data = [_serialize_obj(c) for c in clients] if clients else []
        # default=str is a final safety net for any edge-case types
        await redis.setex(
            f"clients:tenant_{tenant_id}:archived_{archived}",
            CACHE_TTL,
            json.dumps(data, default=str)
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to write client cache: {e}")


async def invalidate_client_cache(tenant_id: int) -> None:
    redis = await get_redis()
    if not redis:
        return

    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"clients:tenant_{tenant_id}:*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate client cache: {e}")
