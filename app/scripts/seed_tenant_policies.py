import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.db.database import SessionLocal
from app.models.tenant_policies import TenantPolicy, DEFAULT_POLICIES
from app.models.tenants import Tenant


def seed_policies_for_existing_tenants():
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            existing = db.query(TenantPolicy).filter(
                TenantPolicy.tenant_id == tenant.id
            ).count()
            if existing == 0:
                print(f"Seeding policies for tenant {tenant.id} — {tenant.name}")
                for policy_data in DEFAULT_POLICIES:
                    policy = TenantPolicy(
                        tenant_id=tenant.id,
                        section=policy_data["section"],
                        title=policy_data["title"],
                        content=policy_data["content"],
                        display_order=policy_data["display_order"],
                        is_active=True,
                    )
                    db.add(policy)
                db.commit()
                print(f"  ✓ 6 policies seeded")
            else:
                print(f"Tenant {tenant.id} already has {existing} policies — skipping")
    finally:
        db.close()


if __name__ == "__main__":
    seed_policies_for_existing_tenants()