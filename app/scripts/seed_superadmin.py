import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.db.database import SessionLocal
from app.core.security import get_password_hash, normalize_email
from app.models.users import User
from app.models.users import UserRole
from app.core.config import get_settings

settings = get_settings()

def update_password():
    db = SessionLocal()
    try:
        email = "admin@superadmin.com"
        password = settings.superadmin_password[:72]  # ← always use this
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                full_name="Super Admin",
                email=email,
                password_hash=get_password_hash(password),  # ← fixed
                role=UserRole.super_admin,
                tenant_id=None,
                is_active=True,
                is_suspended=False,
            )
            db.add(user)
            db.commit()
            print("Super admin created successfully.")
            return
        user.full_name = user.full_name or "Super Admin"
        user.email = email
        user.role = UserRole.super_admin
        user.tenant_id = None
        user.is_active = True
        user.is_suspended = False
        user.password_hash = get_password_hash(password)  # ← fixed
        db.commit()
        print("Password updated successfully.")
    finally:
        db.close()

if __name__ == "__main__":
    update_password()
