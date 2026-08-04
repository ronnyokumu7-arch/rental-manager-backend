"""
Seed default role templates for common job titles.
Run this after deploying to populate the permissions matrix.

Usage:
    python scripts/seed_role_templates.py
"""
import sys
import os
import asyncio

# Ensure the root directory is in the path so 'app' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.db.database import AsyncSessionLocal
from app.core.permissions import ALL_PERMISSION_KEYS

# ✅ CRITICAL FIX: Import the models package once so SQLAlchemy registers all ORM classes
# before any mapper configuration needs to resolve string-based relationships.
import app.models  # noqa: F401

from app.models.role_template import RoleTemplate
from app.models.tenants import Tenant

# Default role templates with sensible permission sets
DEFAULT_ROLE_TEMPLATES = {
    "Director": {
        "description": "Top-level executive with full agency access",
        "permissions": ALL_PERMISSION_KEYS,  # Full access
    },
    "Manager": {
        "description": "Operational manager with broad access",
        "permissions": [
            "view_dashboard",
            "view_clients", "manage_clients",
            "view_vehicles", "manage_vehicles",
            "view_bookings", "manage_bookings",
            "view_contracts", "manage_contracts",
            "view_financials", "record_payments",
            "view_team", "manage_team",
            "view_reports",
        ],
    },
    "HR": {
        "description": "Human resources administrator",
        "permissions": [
            "view_dashboard",
            "view_team", "manage_team",
            "view_clients",
            "view_bookings",
            "view_financials",
        ],
    },
    "Accountant": {
        "description": "Financial officer",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings",
            "view_financials", "record_payments",
            "view_reports",
            "view_contracts",
        ],
    },
    "Cashier": {
        "description": "Payment processing staff",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings",
            "record_payments",
        ],
    },
    "Credit Control": {
        "description": "Collections and accounts receivable",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_financials",
            "view_reports",
        ],
    },
    "Fleet Manager": {
        "description": "Vehicle operations manager",
        "permissions": [
            "view_dashboard",
            "view_vehicles", "manage_vehicles", "manage_maintenance",
            "view_bookings", "manage_bookings",
            "view_clients",
        ],
    },
    "Driver": {
        "description": "Vehicle operator - minimal access",
        "permissions": [
            "view_dashboard",
            "view_bookings",  # Can only see assigned bookings
        ],
    },
    "Dispatcher": {
        "description": "Booking coordinator",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings", "manage_bookings",
            "view_vehicles",
            "view_contracts",
        ],
    },
    "Call Center": {
        "description": "Customer service representative",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings", "manage_bookings",
            "view_vehicles",
        ],
    },
    "Sales Rep": {
        "description": "Sales representative",
        "permissions": [
            "view_dashboard",
            "view_clients", "manage_clients",
            "view_bookings", "manage_bookings",
            "view_vehicles",
            "view_contracts", "manage_contracts",
        ],
    },
    "Booking Agent": {
        "description": "Reservation specialist",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings", "manage_bookings",
            "view_vehicles",
        ],
    },
    "Customer Care": {
        "description": "Customer support",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings",
            "view_contracts",
        ],
    },
    "Contracts Officer": {
        "description": "Contract administrator",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings",
            "view_contracts", "manage_contracts",
        ],
    },
    "Marketing Lead": {
        "description": "Marketing manager",
        "permissions": [
            "view_dashboard",
            "view_clients",
            "view_bookings",
            "view_reports",
        ],
    },
    "Partnerships Manager": {
        "description": "Business development",
        "permissions": [
            "view_dashboard",
            "view_clients", "manage_clients",
            "view_bookings",
            "view_reports",
        ],
    },
}


async def seed_role_templates(tenant_id: int):
    """Create default role templates for a tenant."""
    print(f"Seeding role templates for tenant {tenant_id}...")
    
    async with AsyncSessionLocal() as db:
        try:
            created_count = 0
            for job_title, template_data in DEFAULT_ROLE_TEMPLATES.items():
                # ✅ ASYNC: Check if template already exists
                existing_stmt = select(RoleTemplate).where(
                    RoleTemplate.tenant_id == tenant_id,
                    RoleTemplate.job_title == job_title
                )
                existing_result = await db.execute(existing_stmt)
                existing = existing_result.scalars().first()
                
                if not existing:
                    template = RoleTemplate(
                        tenant_id=tenant_id,
                        job_title=job_title,
                        permissions=template_data["permissions"],
                    )
                    db.add(template)
                    created_count += 1
                    print(f"  ✓ Created template: {job_title}")
                else:
                    print(f"  - Skipped (exists): {job_title}")
            
            await db.commit()
            print(f"✅ Seeded {created_count} role templates for tenant {tenant_id}")
            
        except Exception as e:
            print(f" Error seeding role templates: {e}")
            await db.rollback()


async def main():
    """Main entry point - seeds templates for all existing tenants."""
    async with AsyncSessionLocal() as db:
        # Get all tenants
        tenants_stmt = select(Tenant)
        tenants_result = await db.execute(tenants_stmt)
        tenants = tenants_result.scalars().all()
        
        if not tenants:
            print(" No tenants found. Create a tenant first.")
            return
        
        print(f"Found {len(tenants)} tenant(s)")
        
        for tenant in tenants:
            await seed_role_templates(tenant.id)


if __name__ == "__main__":
    asyncio.run(main())
