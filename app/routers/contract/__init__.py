"""
Contract router package - contains all contract-related endpoints.
"""
from fastapi import APIRouter
from . import management, actions, public

router = APIRouter(prefix="/contracts", tags=["contracts"])

# Include all sub-routers
router.include_router(management.router)
router.include_router(actions.router)
router.include_router(public.router)
