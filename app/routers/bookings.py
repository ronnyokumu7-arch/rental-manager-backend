# app/routers/bookings.py

from fastapi import APIRouter

from .booking import management, lifecycle, invoices, extensions, contracts

router = APIRouter(prefix="/bookings", tags=["bookings"])

# Include all booking sub-routers
router.include_router(management.router)
router.include_router(lifecycle.router)
router.include_router(invoices.router)
router.include_router(extensions.router)
router.include_router(contracts.router)
