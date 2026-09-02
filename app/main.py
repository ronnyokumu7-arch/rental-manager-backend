# app/main.py
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
from app.db.database import test_db_connection

from app.routers import (
    activity_logs,
    admin,
    airport_transfer,
    auth,
    bookings,
    client_invites,
    clients,
    commission,
    contracts,
    drivers,
    files,
    financials,
    health,
    invoices,
    payment_verifications,
    payments,
    pricing,
    reports,
    role_templates,
    services,
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

# ✅ NEW: Cache management router (super_admin only)
from app.routers.admin.cache_management import router as cache_management_router

from app.endpoints.health import router as agency_health_router

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ✅ 1. TEST DATABASE CONNECTIVITY FIRST
    db_ok = await test_db_connection()
    if not db_ok:
        print("⚠️ WARNING: Database connection failed at startup. The app will continue, but authenticated requests will fail.")
        print("   Check that DATABASE_URL points to a resolvable hostname (same region as this web service).")
    
    # ✅ 2. Initialize Redis cache using the centralized fail-safe client
    try:
        from app.core.redis_client import init_redis, get_redis, close_redis
        await init_redis()
        redis_client = await get_redis()
        
        if redis_client:
            FastAPICache.init(RedisBackend(redis_client), expire=300)
            print("✅ FastAPICache initialized with Redis backend")
        else:
            print("⚠️ Redis unavailable — cache operations will be no-ops")
    except Exception as e:
        print(f"⚠️ Redis initialization warning: {e}")

    # ✅ 3. Pre-warm the headless browser
    if not settings.debug:
        try:
            from app.services.browser_pool import browser_pool
            await browser_pool.get_browser()
            print("✅ Headless Chrome is pre-warmed and ready for PDF generation!")
        except Exception as e:
            print(f"⚠️ Browser pre-warm warning: {e}")

    # ✅ 4. Start background scheduler
    start_scheduler()
    
    yield
    
    # ─── SHUTDOWN PHASE ─────────────────────────────────────────────────────
    print("🔄 Shutting down application gracefully...")
    
    stop_scheduler()
    
    try:
        from app.services.browser_pool import browser_pool
        await browser_pool.close()
        print("✅ Headless Chrome closed gracefully.")
    except Exception as e:
        print(f"⚠️ Browser shutdown warning: {e}")
    
    try:
        from app.core.redis_client import close_redis
        await close_redis()
    except Exception as e:
        print(f"⚠️ Redis shutdown warning: {e}")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)

@app.get("/")
def root():
    return {
        "message": "Rental Garage API is running",
        "docs": "/docs",
        "health": "/api/v1/health",
    }

routers = [
    auth,
    tenants,
    users,
    client_invites,
    clients,
    commission,
    vehicles,
    drivers,
    airport_transfer,
    bookings,
    subscriptions,
    invoices,
    payments,
    payment_verifications,
    pricing,
    tenant_profile,
    tenant_policies,
    role_templates,
    services,
    contracts,
    financials,
    admin,
    reports,
    activity_logs,
    tasks,
    system,
    user_preferences,
    vault,
    files,
    health,
]

for router in routers:
    app.include_router(router.router, prefix="/api/v1")

# ✅ NEW: Register cache management router under /api/v1/admin/cache
app.include_router(cache_management_router, prefix="/api/v1/admin")

app.include_router(agency_health_router, prefix="/api/v1")
