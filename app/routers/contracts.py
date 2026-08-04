"""
Contracts Orchestrator
Aggregates all contract-related sub-routers into a single entry point.
"""
from fastapi import APIRouter

# Import the sub-routers from the contract package
from app.routers.contract import management, actions, public

# Create the main router (prefix and tags are defined here)
router = APIRouter(prefix="/contracts", tags=["contracts"])

# Include all sub-routers
# Note: The sub-routers themselves do NOT have prefixes, so they inherit this one.
router.include_router(management.router)
router.include_router(actions.router)
router.include_router(public.router)
