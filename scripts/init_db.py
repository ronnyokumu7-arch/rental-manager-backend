# scripts/init_db.py
import asyncio
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine
from app.db.database import Base
from app.core.config import get_settings

# Import ALL models so SQLAlchemy registers them with Base.metadata
import app.models.users
import app.models.tenants
import app.models.bookings
import app.models.vehicles
import app.models.clients
import app.models.invoices
import app.models.payments
import app.models.contracts
import app.models.task
import app.models.activity_log
import app.models.role_template
import app.models.subscriptions
import app.models.tenant_policies
import app.models.tenant_profile
import app.models.refresh_tokens
import app.models.password_reset
import app.models.payment_gateways

async def init_db():
    settings = get_settings()
    print(f" Connecting to database...")
    
    engine = create_async_engine(settings.database_url)
    
    try:
        async with engine.begin() as conn:
            # ✅ SAFE: Only creates tables that don't exist. Won't touch existing data.
            print("🏗️ Creating missing tables from models...")
            await conn.run_sync(Base.metadata.create_all)
            print("✅ Database tables initialized successfully!")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_db())