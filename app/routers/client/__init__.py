"""
Client router module - aggregates all client-related endpoints.
"""
from fastapi import APIRouter
from . import management, documents, lifecycle

router = APIRouter(prefix="/clients", tags=["clients"])

# Include all sub-routers
router.include_router(management.router)
router.include_router(documents.router)
router.include_router(lifecycle.router)
