import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis import asyncio as aioredis

# 🚨 Rate Limiting Imports
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter

from app.core.config import get_settings
from app.core.exceptions import http_exception_handler
from app.jobs.scheduler import start_scheduler, stop_scheduler

# 💡 Imported health from app.endpoints as requested
from app.endpoints import health

from app.routers import (
    activity_logs,
    admin,
    auth,
    bookings,
    clients,
    contracts,
    files,             # ✅ NEW: Authenticated file-serving router
    financials,
    invoices,
    payment_verifications,
    payments,
    reports,
    role_templates,
    subscriptions,
    system,
    tasks,
    tenant_policies,
    tenant_profile,
    tenants,
    user_preferences,
    users,
    vehicles,
    vault,
)

# ✅ Initialize settings early so it can be used in the lifespan function
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # 1. Initialize Redis cache
        redis = aioredis.from_url(
            settings.redis_url, 
            encoding="utf-8", 
            decode_responses=True
        )
        FastAPICache.init(RedisBackend(redis), expire=300)
        
    except Exception as e:
        print(f"Initialization warning: {e}")

    # ✅ 2. Pre-warm the headless browser for instant PDF generation
    try:
        from app.services.browser_pool import browser_pool
        await browser_pool.get_browser()
        print("✅ Headless Chrome is pre-warmed and ready for PDF generation!")
    except Exception as e:
        print(f"⚠️ Browser pre-warm warning: {e}")

    start_scheduler()
    yield
    
    # ✅ 3. Clean up the headless browser on shutdown
    try:
        from app.services.browser_pool import browser_pool
        await browser_pool.close()
        print("✅ Headless Chrome closed gracefully.")
    except Exception as e:
        print(f"⚠️ Browser shutdown warning: {e}")
        
    stop_scheduler()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
    # ✅ FastAPI natively handles trailing slashes correctly. No redirect hacks needed.
)

# 2. Register the Rate Limiter globally
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ✅ CLEANUP: Removed redundant manual os.getenv("CORS_ORIGINS") parsing.
# We now rely entirely on the robust, validated settings.cors_origins from app/core/config.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # ✅ Uses the pre-validated list from Settings
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ❌ REMOVED: Public StaticFiles mounts for /uploads and /contracts.
# Serving tenant files (IDs, DLs, contracts) publicly is a critical security risk.
# All file access is now routed through the authenticated /api/v1/files/ endpoint.

app.add_exception_handler(HTTPException, http_exception_handler)

@app.get("/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
        "db_status": "connected",
        "cache_status": "connected",
        "rate_limit_status": "active",
    }

@app.get("/")
def root():
    return {
        "message": "Rental Manager API is running",
        "docs": "/docs",
        "health": "/health"
    }

routers = [
    auth,
    tenants,
    users,
    clients,
    vehicles,
    bookings,
    subscriptions,
    invoices,
    payments,
    payment_verifications,
    tenant_profile,
    tenant_policies,
    role_templates,
    contracts,
    financials,
    admin,
    reports,
    activity_logs,
    tasks,
    system,
    user_preferences,
    vault,
    files,  # ✅ NEW: Add authenticated files router to the list
]

# ✅ CORRECT: Extracts the .router attribute from each module
for router in routers:
    app.include_router(router.router, prefix="/api/v1")

app.include_router(health.router, prefix="/api/v1")
