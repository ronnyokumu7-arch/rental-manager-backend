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

from app.routers import (
    activity_logs,
    admin,
    auth,
    bookings,
    client_invites,
    clients,
    commission,
    contracts,
    drivers,
    files,
    financials,
    health,             # ✅ System health endpoint (lightweight, no auth)
    invoices,
    payment_verifications,
    payments,
    pricing,            # ✅ Phase 1: Self-drive quote endpoint
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

# ✅ FIX: Agency Health router was orphaned in app/routers/endpoints/health.py
# It was never imported, so FastAPI never registered /tenants/{id}/health → 404.
from app.endpoints.health import router as agency_health_router

# ✅ Initialize settings early
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

    # ✅ 2. Pre-warm the headless browser
    try:
        from app.services.browser_pool import browser_pool
        await browser_pool.get_browser()
        print("✅ Headless Chrome is pre-warmed and ready for PDF generation!")
    except Exception as e:
        print(f"⚠️ Browser pre-warm warning: {e}")

    # ✅ 3. Start background scheduler
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

# Register Rate Limiter globally
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ✅ CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)

# ✅ Root endpoint (keep simple)
@app.get("/")
def root():
    return {
        "message": "Rental Garage API is running",
        "docs": "/docs",
        "health": "/api/v1/health",
    }

# ✅ Register all API routers
routers = [
    auth,
    tenants,
    users,
    client_invites,
    clients,
    commission,
    vehicles,
    drivers,
    bookings,
    subscriptions,
    invoices,
    payments,
    payment_verifications,
    pricing,            # ✅ Phase 1: Self-drive quote → POST /api/v1/pricing/self-drive/quote
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
    health,  # ✅ System health router → /api/v1/health
]

for router in routers:
    app.include_router(router.router, prefix="/api/v1")

# ✅ FIX: Register the Agency Health router (it carries its own /tenants prefix)
# → GET /api/v1/tenants/{tenant_id}/health  (super_admin only, 30/min)
# Registered AFTER the loop so its specific path can never be shadowed by
# generic dynamic routes inside the tenants router.
app.include_router(agency_health_router, prefix="/api/v1")
