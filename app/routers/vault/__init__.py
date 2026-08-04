# app/routers/vault/__init__.py

from fastapi import APIRouter

from . import bookings
from . import clients
from . import tenants
from . import vehicles
from . import tasks
from . import users
from . import payments
from . import financials

# Main Vault Router
router = APIRouter(prefix="/vault", tags=["vault"])

router.include_router(bookings.router)
router.include_router(clients.router)
router.include_router(tenants.router)
router.include_router(vehicles.router)
router.include_router(tasks.router)
router.include_router(users.router)
router.include_router(payments.router)
router.include_router(financials.router)
