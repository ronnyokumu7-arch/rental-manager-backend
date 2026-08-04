"""
Payment router package - contains all payment-related endpoints.
"""
from fastapi import APIRouter
from . import management, actions

# Define the prefix and tags here
router = APIRouter(prefix="/payments", tags=["payments"])

# Include all sub-routers
router.include_router(management.router)
router.include_router(actions.router)
