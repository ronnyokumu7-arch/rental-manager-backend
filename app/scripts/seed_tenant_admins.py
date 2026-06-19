import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import get_settings
from app.core.security import get_password_hash, normalize_email
from app.db.database import SessionLocal
from app.models.users import User, UserRole


settings = get_settings()


def seed_tenant_admin_passwords():
    db = SessionLocal()
    try:
        tenant_admins = db.query(User).filter(User.role == UserRole.tenant_admin).all()

        if not tenant_admins:
            print("No tenant admin users found.")
            return

        password_hash = get_password_hash(settings.tenant_admin_password[:72])

        for user in tenant_admins:
            user.email = normalize_email(user.email)
            user.is_active = True
            user.is_suspended = False
            user.suspension_reason = None
            user.password_hash = password_hash
            print(f"Updated tenant admin: {user.email}")

        db.commit()
        print(f"Updated {len(tenant_admins)} tenant admin account(s).")
    finally:
        db.close()


if __name__ == "__main__":
    seed_tenant_admin_passwords()
