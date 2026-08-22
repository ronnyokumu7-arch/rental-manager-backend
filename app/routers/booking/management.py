# app/routers/booking/management.py
"""
Booking management — combiner.

Endpoints live in focused modules; this file only assembles them so the
existing registration (`management.router`) keeps working unchanged.

Route order is preserved: READ → QUOTE → CREATE → LIFECYCLE.
"""
from fastapi import APIRouter

from . import management_read
from . import management_create
from . import management_lifecycle

router = APIRouter()
router.include_router(management_read.router)
router.include_router(management_create.router)
router.include_router(management_lifecycle.router)
