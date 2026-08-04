import asyncio
from sqlalchemy import text
from app.db.database import engine, Base

# Import ALL models so SQLAlchemy knows they exist
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
    print("🧹 Nuking the 'public' schema to ensure a 100% clean slate...")
    async with engine.begin() as conn:
        # Drop the public schema and EVERYTHING in it (tables, indexes, constraints)
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
        await conn.execute(text("CREATE SCHEMA public;"))
        print("✅ Schema wiped completely clean.")
        
        print("🏗️ Creating fresh database tables from models...")
        await conn.run_sync(Base.metadata.create_all)
        
    print("✅ Database schema initialized successfully!")

if __name__ == "__main__":
    asyncio.run(init_db())
