import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.db.database import SessionLocal
from app.core.security import get_password_hash
from app.models.users import User, UserRole
from app.core.config import get_settings

settings = get_settings()

def update_password():
    db = SessionLocal()
    try:
        # Read from environment variables (with fallback defaults)
        email = os.getenv("SUPERADMIN_EMAIL", "royride.ke@gmail.com")
        password = os.getenv("SUPERADMIN_PASSWORD", settings.superadmin_password)[:72]
        
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            # CREATE: Only runs once when the user doesn't exist
            user = User(
                full_name="Super Admin",
                email=email,
                password_hash=get_password_hash(password),
                role=UserRole.super_admin,
                tenant_id=None,
                is_active=True,
                is_suspended=False,
            )
            db.add(user)
            db.commit()
            print(f"✅ Super admin created: {email}")
            return
        
        # UPDATE: Only runs if you explicitly want to reset
        # Uncomment the next 3 lines ONLY if you're locked out and need to reset
        # user.password_hash = get_password_hash(password)
        # db.commit()
        # print(f"🔄 Password reset for: {email}")
        
        print(f"ℹ️ Super admin already exists: {email} (skipping)")
        
    except Exception as e:
        print(f"❌ Error seeding super admin: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    update_password()
