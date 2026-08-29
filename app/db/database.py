# app/db/database.py
import logging
from urllib.parse import urlparse, urlunparse

from sqlalchemy import Column, DateTime, Integer, ForeignKey, text
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# 1. Smart URL formatting: Ensure we use the asyncpg driver
#    (Redundant safety — config.py already converts, but belt-and-braces)
# ─────────────────────────────────────────────────────────────────────────────
db_url = settings.database_url
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Sanitized URL for logging (redact password, keep host for diagnostics)
# ─────────────────────────────────────────────────────────────────────────────
def _sanitize_url(url: str) -> str:
    """Return URL with password redacted, for safe logging."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            # Replace password with *** in the netloc
            netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            return urlunparse(parsed._replace(netloc=netloc))
        return url
    except Exception:
        return "<unparseable-url>"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Production-Grade Async Connection Pooling
#    Tuned for Render Postgres (5-min idle timeout, not 60-min)
# ─────────────────────────────────────────────────────────────────────────────
engine = create_async_engine(
    db_url,
    echo=False,  # Set to True ONLY for local debugging, False in production
    pool_size=20,                # Keep 20 connections always open and ready
    max_overflow=30,             # Allow 30 extra connections during sudden spikes (Total 50)
    pool_pre_ping=True,          # ✅ Verify connection is alive before using it
    pool_recycle=270,            # ✅ Render Postgres idle timeout is ~5min; recycle at 4.5min
    pool_timeout=30,             # Max seconds to wait for a connection from the pool
)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Async Session Factory
# ─────────────────────────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,      # ⚠️ CRUCIAL: Prevents "Object is no longer bound to session" errors in async
    autocommit=False,
    autoflush=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Base class for declarative models
# ─────────────────────────────────────────────────────────────────────────────
Base = declarative_base()

# ─────────────────────────────────────────────────────────────────────────────
# 6. ✅ PRODUCTION-READY AUDIT MIXIN
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# 7. ✅ STARTUP CONNECTIVITY TEST
#    Run once at boot. Catches DNS/connection issues immediately with a
#    clear, actionable error message instead of cryptic asyncpg tracebacks.
# ─────────────────────────────────────────────────────────────────────────────
async def test_db_connection() -> bool:
    """
    Test database connectivity at startup.

    Returns True if connected, False otherwise.
    Logs the sanitized URL (password redacted) for quick diagnosis.
    """
    sanitized = _sanitize_url(db_url)
    logger.info(f"🔗 Testing database connection: {sanitized}")

    try:
        async with engine.begin() as conn:
            # Simple ping that doesn't require any table to exist
            result = await conn.execute(text("SELECT 1"))
            result.scalar()
        logger.info("✅ Database connection verified successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {type(e).__name__}: {e}")
        logger.error(f"   URL: {sanitized}")
        logger.error("   Action: Check that DATABASE_URL host is resolvable from this service")
        logger.error("   Render: Verify the Postgres instance is in the same region as this web service")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 8. FastAPI Dependency for getting async DB sessions
#    Auto-commits on success as a safety net for endpoints that forget to commit.
#    Endpoints that explicitly commit are unaffected (second commit is a no-op).
# ─────────────────────────────────────────────────────────────────────────────
async def get_db() -> AsyncSession:
    """
    Dependency to get an async database session.
    Ensures the session is properly committed/rolled back and closed after the request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Safety net: auto-commit if endpoint didn't explicitly commit
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # `async with` already closes the session — no explicit close needed
