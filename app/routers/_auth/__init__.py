"""
Auth router package - contains all authentication-related endpoints.
"""
from fastapi import APIRouter
from . import session, me, password_reset, sessions

# Define the prefix and tags here
router = APIRouter(prefix="/auth", tags=["auth"])

# Include all sub-routers
router.include_router(session.router)
router.include_router(me.router)
router.include_router(password_reset.router)
router.include_router(sessions.router)
