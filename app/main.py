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
    redis_client = None
    
    try:
        # 1. Initialize Redis cache
        redis_client = aioredis.from_url(
            settings.redis_url, 
            encoding="utf-8", 
            decode_responses=True
        )
        FastAPICache.init(RedisBackend(redis_client), expire=300)
        
    except Exception as e:
        print(f"⚠️ Redis initialization warning: {e}")

    # ✅ 2. Pre-warm the headless browser for instant PDF generation
    try:
        from app.services.browser_pool import browser_pool
        await browser_pool.get_browser()
        print("✅ Headless Chrome is pre-warmed and ready for PDF generation!")
    except Exception as e:
        print(f"⚠️ Browser pre-warm warning: {e}")

    # ✅ 3. Start background scheduler
    start_scheduler()
    
    # Yield control to the application
    yield
    
    # ─── SHUTDOWN PHASE ─────────────────────────────────────────────────────
    print("🔄 Shutting down application gracefully...")
    
    # Stop scheduler
    stop_scheduler()
    
    # Close browser pool
    try:
        from app.services.browser_pool import browser_pool
        await browser_pool.close()
        print("✅ Headless Chrome closed gracefully.")
    except Exception as e:
        print(f"⚠️ Browser shutdown warning: {e}")
        
    # Close Redis connection to prevent Docker/Render connection leaks
    if redis_client:
        try:
            await redis_client.close()
            print("✅ Redis connection closed.")
        except Exception as e:
            print(f"⚠️ Redis shutdown warning: {e}")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# 2. Register the Rate Limiter globally
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ✅ CORS Middleware
# ⚠️ IMPORTANT: Ensure settings.cors_origins returns a LIST of strings, 
# not a comma-separated string. FastAPI's CORSMiddleware requires a list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app", # ✅ NEW: Allows ANY Vercel deployment (preview or prod)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)

@app.get("/health", tags=["system"])
def health_check():
    # Render's health check only needs a 200 OK response.
    # Keep this lightweight to avoid blocking the event loop.
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
        "message": "Rental Garage API is running",
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
    files,
]

# ✅ CORRECT: Extracts the .router attribute from each module
for router in routers:
    app.include_router(router.router, prefix="/api/v1")

app.include_router(health.router, prefix="/api/v1")
