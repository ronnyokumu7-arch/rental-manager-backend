# app/routers/__init__.py

from . import admin
from . import auth
from . import airport_transfer
from . import bookings
from . import clients
from . import client_vetting
from . import contracts
from . import drivers
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
from . import vault
from . import services

__all__ = [
    "admin",
    "auth",
    "airport_transfer",
    "bookings",
    "clients",
    "client_vetting",
    "contracts",
    "drivers",
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
    "vault",
    "services",
]
