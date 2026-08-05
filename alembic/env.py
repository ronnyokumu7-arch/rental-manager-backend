import asyncio
import os
import importlib
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine import engine_from_config
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.db.database import Base
from app.core.config import get_settings

# ─────────────────────────────────────────────────────────────────────────────
# 1. VALIDATE DATABASE_URL EARLY
# ─────────────────────────────────────────────────────────────────────────────
# Alembic needs DATABASE_URL to run. Fail fast with a helpful message.
settings = get_settings()
if not settings.database_url:
    print("❌ ERROR: DATABASE_URL environment variable is not set.")
    print("   Set it in Render Dashboard or your .env file.")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 2. DYNAMIC MODEL IMPORTS (with fallback)
# ─────────────────────────────────────────────────────────────────────────────
models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app', 'models'))

# First, try dynamic import (your existing logic)
for filename in os.listdir(models_dir):
    if filename.endswith('.py') and not filename.startswith('__'):
        module_name = f"app.models.{filename[:-3]}"
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            print(f"⚠️ Warning: Could not dynamically import {module_name}: {e}")

# Import models from subdirectories (e.g., payment_gateways/)
for subdir in os.listdir(models_dir):
    subdir_path = os.path.join(models_dir, subdir)
    if os.path.isdir(subdir_path) and not subdir.startswith('__'):
        for filename in os.listdir(subdir_path):
            if filename.endswith('.py') and not filename.startswith('__'):
                module_name = f"app.models.{subdir}.{filename[:-3]}"
                try:
                    importlib.import_module(module_name)
                except ImportError as e:
                    print(f"⚠️ Warning: Could not dynamically import {module_name}: {e}")

# Fallback: Explicitly import known models if dynamic loading misses any
# This prevents "table not found" errors during autogenerate
try:
    from app.models import user, client, vehicle, booking, invoice, payment, contract, task, tenant, subscription
except ImportError:
    # If individual imports fail, that's okay — dynamic loading may have succeeded
    pass

# ─────────────────────────────────────────────────────────────────────────────
# 3. ALEMBIC CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """
    Convert async database URL to sync driver for Alembic.
    Alembic's migration context is synchronous, so we use psycopg (not asyncpg).
    """
    url = settings.database_url
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection)."""
    url = get_sync_url()
    print(f"🔄 Running migrations in OFFLINE mode with URL: {url[:30]}...")
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Better support for SQLite and some DBs
    )
    
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure context and run migrations with a live connection."""
    context.configure(
        connection=connection, 
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with DB connection)."""
    url = get_sync_url()
    print(f"🔄 Running migrations in ONLINE mode with URL: {url[:30]}...")
    
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = url
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Correct for short-lived migration connections
    )
    
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()