"""
Invoice router package - contains all invoice-related endpoints.
"""
from fastapi import APIRouter
from . import admin, public

# Define the prefix and tags here
router = APIRouter(prefix="/invoices", tags=["invoices"])

# Include all sub-routers
router.include_router(admin.router)
router.include_router(public.router)
