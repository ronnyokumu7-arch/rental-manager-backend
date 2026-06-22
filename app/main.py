from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import http_exception_handler
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers import (
    admin, auth, bookings, clients, contracts,
    invoices, payments, reports, subscriptions,
    tenant_policies, tenant_profile, tenants, 
    users, vehicles,
)
from app.scripts.seed_superadmin import update_password
from app.scripts.seed_tenant_admins import seed_tenant_admin_passwords
from app.scripts.seed_tenant_policies import seed_policies_for_existing_tenants

app = FastAPI(title="Rental Manager", version="1.0.0")

from fastapi.staticfiles import StaticFiles
import os

# Mount the uploads directory for serving files
if os.path.exists("./uploads"):
    app.mount("/uploads", StaticFiles(directory="./uploads"), name="uploads")


# 1. Modern Lifespan Manager (replaces @app.on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("Running seed initialization...")
    try:
        update_password()
        seed_tenant_admin_passwords()
        seed_policies_for_existing_tenants()
        print("Seed initialization completed.")
    except Exception as e:
        print(f"Warning: Seed initialization encountered an error: {e}")
    
    start_scheduler()
    yield
    # Shutdown logic
    stop_scheduler()

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# 2. Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Global Exception Handler
app.add_exception_handler(HTTPException, http_exception_handler)

# 4. Health Check
@app.get("/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
    }

# 5. Include Routers
routers = [
    auth, tenants, users, clients, vehicles,
    bookings, subscriptions, invoices, payments,
    tenant_profile, tenant_policies, contracts,
    admin, reports
]

for router in routers:
    app.include_router(router.router, prefix="/api/v1")