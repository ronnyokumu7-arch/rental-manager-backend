# app/api/health.py
from fastapi import APIRouter
from datetime import datetime, timezone

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
        "version": "1.0.0"
    }

@router.get("/health/deep")
async def deep_health_check():
    """
    Deep health check that verifies database and Redis connectivity.
    Use this for deployment verification, not frequent monitoring.
    """
    from app.core.database import get_db
    from app.core.redis_client import get_redis
    
    checks = {
        "database": False,
        "redis": False,
    }
    
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        pass
    
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = True
    except Exception:
        pass
    
    status = "healthy" if all(checks.values()) else "degraded"
    
    return {
        "status": status,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
