from slowapi import Limiter
from fastapi import Request
from app.core.config import get_settings

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
        return forwarded_for.split(",")[0].strip()
    
    # 2. Check X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # 3. Fallback to direct connection IP
    if request.client and request.client.host:
        return request.client.host
    
    return "unknown"


# 🚀 CRITICAL: Using Redis storage ensures rate limits are accurate 
# even if you run multiple Gunicorn workers or scale horizontally.
# Using get_client_ip prevents a single user from blocking the entire proxy IP.
limiter = Limiter(
    key_func=get_client_ip,  # ✅ UPDATED: Safe proxy-aware IP extraction
    storage_uri=settings.redis_url,
    strategy="moving-window"  # Smoother, more accurate than fixed-window
)
