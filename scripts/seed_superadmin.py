import sys
import os
import asyncio  

# Ensure the root directory is in the path so 'app' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.users import User, UserRole
from app.core.config import get_settings  # ← Updated to accept _env_file param
from sqlalchemy import select

# ✅ FIX: Import the models package once so SQLAlchemy registers all ORM classes
import app.models  # noqa: F401

# 🔧 KEY CHANGE: Ignore .env files, use ONLY system environment variables
# This ensures we seed the Render DB (via export DATABASE_URL=...), not local
settings = get_settings(_env_file=None)

async def seed_superadmin():
    # 🔍 DEBUG: Log which database we're connecting to
    db_url = settings.database_url
    if "localhost" in db_url or "127.0.0.1" in db_url:
        print(f"⚠️  CONNECTING TO LOCAL DB: {db_url[:60]}...")
    else:
        print(f"✅ CONNECTING TO REMOTE DB: {db_url[:60]}...")
    
    # 'async with' handles opening and closing the connection automatically
    async with AsyncSessionLocal() as db:
        try:
            email = os.getenv("SUPERADMIN_EMAIL", "admin@example.com")
            password = os.getenv("SUPERADMIN_PASSWORD", settings.superadmin_password)
            
            # Fetch user
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            
            if not user:
                # CREATE
                user = User(
                    full_name="System Super Admin",
                    email=email,
                    password_hash=get_password_hash(password),
                    role=UserRole.super_admin,
                    tenant_id=None,
                    is_active=True,
                    is_suspended=False,
                    email_verified=True, # Super admin is auto-verified
                )
                db.add(user)
                await db.commit() 
                print(f"✅ Super admin created successfully: {email}")
                return
            
            print(f"ℹ️ Super admin already exists: {email} (skipping)")
            
        except Exception as e:
            print(f"❌ Error seeding super admin: {e}")
            await db.rollback() # Good practice to rollback on error

if __name__ == "__main__":
    # This runs the async function properly from a normal script
    asyncio.run(seed_superadmin())