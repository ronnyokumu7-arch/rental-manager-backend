# app/api/health.py
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from app.db.database import async_session_maker
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """
    Lightweight health check for monitoring services.
    Returns instantly without database or Redis calls.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@router.get("/health/deep")
async def deep_health_check():
    """
    Deep health check that verifies database and Redis connectivity.
    Use this for deployment verification, not frequent monitoring.
    Never raises — reports 'degraded' when a dependency is unavailable.
    """
    checks = {
        "database": False,
        "redis": False,
    }

    # ✅ DB check: use the async session maker directly (not the FastAPI dependency)
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            checks["database"] = True
    except Exception as e:
        logger.warning(f"⚠️ Deep health check — database unavailable: {e}")

    # ✅ Redis check: get_redis() returns None when unavailable (not a client)
    try:
        redis = await get_redis()
        if redis is not None:
            await redis.ping()
            checks["redis"] = True
        else:
            logger.info("⚠️ Deep health check — Redis unavailable (client returned None)")
    except Exception as e:
        logger.warning(f"⚠️ Deep health check — Redis error: {e}")

    status = "healthy" if all(checks.values()) else "degraded"

    return {
        "status": status,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
