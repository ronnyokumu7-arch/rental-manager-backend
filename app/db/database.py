from sqlalchemy import Column, DateTime, Integer, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

settings = get_settings()

# 1. Smart URL formatting: Ensure we use the asyncpg driver
db_url = settings.database_url
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

# 2. Production-Grade Async Connection Pooling
engine = create_async_engine(
    db_url,
    echo=False,  # Set to True ONLY for local debugging, False in production
    pool_size=20,                # Keep 20 connections always open and ready
    max_overflow=30,             # Allow 30 extra connections during sudden spikes (Total 50)
    pool_pre_ping=True,          # Verify connection is alive before using it
    pool_recycle=3600,           # Recycle connections every 1 hour to prevent DB-side timeouts
    pool_timeout=30,             # Max seconds to wait for a connection from the pool
)

# 3. Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,      # ⚠️ CRUCIAL: Prevents "Object is no longer bound to session" errors in async
    autocommit=False,
    autoflush=False,
)

# 4. Base class for declarative models
Base = declarative_base()

# 5. ✅ PRODUCTION-READY AUDIT MIXIN
class AuditMixin:
    """
    Mixin to add standard audit fields to any SQLAlchemy model.
    Inherit from this alongside Base (e.g., class User(Base, AuditMixin):)
    """
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # created_by is nullable because system processes (cron jobs, seeders, super admin actions) 
    # may create records without a specific user context. Indexed for fast filtering.
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

# 6. FastAPI Dependency for getting async DB sessions
async def get_db() -> AsyncSession:
    """
    Dependency to get an async database session.
    Ensures the session is properly committed/rolled back and closed after the request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
