# app/routers/__init__.py

from . import admin
from . import auth
from . import airport_transfer  # ✅ NEW: Airport Transfer CRUD (Milestone 2)
from . import bookings
from . import clients
from . import contracts
from . import drivers  # ✅ NEW: Staff drivers CRUD (Milestone 2)
from . import invoices
from . import payments
from . import reports
from . import subscriptions
from . import tenant_policies
from . import tenant_profile
from . import tenants
from . import users
from . import vehicles
from . import activity_logs
from . import role_templates
from . import tasks
from . import vault  # ✅ NEW: Add the vault router
from . import services  # ✅ NEW: Service catalog export (Milestone 1.1)

__all__ = [
    "admin",
    "auth",
    "airport_transfer",  # ✅ NEW: Milestone 2
    "bookings",
    "clients",
    "contracts",
    "drivers",  # ✅ NEW: Milestone 2
    "invoices",
    "payments",
    "reports",
    "subscriptions",
    "tenant_policies",
    "tenant_profile",
    "tenants",
    "users",
    "vehicles",
    "activity_logs",
    "role_templates",
    "tasks",
    "vault",  # ✅ NEW
    "services",  # ✅ NEW: Milestone 1.1
]
