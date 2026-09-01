# app/core/limiter.py
import logging
from slowapi import Limiter
from fastapi import Request
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_client_ip(request: Request) -> str:
    """
    Safely extracts the real client IP address, accounting for reverse proxies.
    
    Priority:
    1. X-Forwarded-For (Standard for load balancers like AWS ALB, Render, Nginx)
    2. X-Real-IP (Common in Nginx setups)
    3. Direct connection IP (Fallback for local development or direct exposure)
    """
    # 1. Check X-Forwarded-For (can be a comma-separated list; the first is the original client)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    
    # 2. Check X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        ip = real_ip.strip()
        if ip:
            return ip
    
    # 3. Fallback to direct connection IP
    if request.client and request.client.host:
        return request.client.host
    
    # 4. Absolute fallback (prevents accidental empty strings from grouping all traffic)
    return "unknown-ip"


# 🚀 CRITICAL: Using Redis storage ensures rate limits are accurate 
# even if you run multiple Gunicorn workers or scale horizontally.
# 
# ✅ RESILIENCE FIX: Added storage_options to enforce strict timeouts.
# If Redis is degraded, requests will fail in 1 second instead of hanging 
# for 30 seconds and causing frontend "failed to load" timeouts.
limiter = Limiter(
    key_func=get_client_ip,
    storage_uri=settings.redis_url,
    strategy="moving-window",  # Smoother, more accurate than fixed-window
    storage_options={
        "socket_connect_timeout": 1,  # Fail fast if Redis is unreachable
        "socket_timeout": 1,          # Fail fast if Redis stops responding
        "retry_on_timeout": True,     # Allow redis-py to retry transient network blips
    }
)
