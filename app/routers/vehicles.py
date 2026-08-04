# app/routers/vehicles.py
from fastapi import APIRouter
from .vehicle.management import router as management_router
from .vehicle.lifecycle import router as lifecycle_router

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

router.include_router(management_router)
router.include_router(lifecycle_router)
