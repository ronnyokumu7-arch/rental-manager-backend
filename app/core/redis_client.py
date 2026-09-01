# app/core/redis_client.py
"""
Centralized Redis client with fail-safe connection logic.
Returns None when Redis is unavailable instead of raising exceptions.
"""
import logging
from typing import Optional
from redis import asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None
_redis_available: bool = False


async def init_redis() -> None:
    """Initialize Redis connection pool. Called once at startup."""
    global _redis_client, _redis_available
    
    try:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
        # Test connection
        await _redis_client.ping()
        _redis_available = True
        logger.info("✅ Redis connected successfully")
    except Exception as e:
        logger.warning(f"⚠️ Redis unavailable: {e}. Cache operations will be no-ops.")
        _redis_client = None
        _redis_available = False


async def get_redis() -> Optional[aioredis.Redis]:
    """
    Get Redis client. Returns None if Redis is unavailable.
    Callers must handle None gracefully (fail-open).
    """
    # ✅ FIX: global declaration MUST be at the top of the function,
    # BEFORE any read or write of the variable.
    global _redis_available
    
    if not _redis_available or _redis_client is None:
        return None
    
    # Verify connection is still alive
    try:
        await _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning(f"⚠️ Redis connection lost: {e}")
        _redis_available = False
        return None


async def close_redis() -> None:
    """Gracefully close Redis connection."""
    global _redis_client, _redis_available
    if _redis_client:
        try:
            await _redis_client.close()
            logger.info("✅ Redis connection closed")
        except Exception as e:
            logger.warning(f"⚠️ Error closing Redis: {e}")
        finally:
            _redis_client = None
            _redis_available = False


def is_redis_available() -> bool:
    """Check if Redis is available (cached status, no ping)."""
    return _redis_available
