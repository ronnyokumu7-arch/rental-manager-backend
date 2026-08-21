# app/routers/__init__.py

from . import admin
from . import auth
from . import bookings
from . import clients
from . import contracts
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
    "bookings",
    "clients",
    "contracts",
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
