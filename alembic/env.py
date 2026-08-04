import asyncio
import os
import importlib
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.db.database import Base
from app.core.config import get_settings

# ✅ Dynamically import ALL models — no filename guessing
models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app', 'models'))
for filename in os.listdir(models_dir):
    if filename.endswith('.py') and not filename.startswith('__'):
        module_name = f"app.models.{filename[:-3]}"
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            print(f"⚠️ Warning: Could not import {module_name}: {e}")

# Also import models from subdirectories (e.g., payment_gateways/)
for subdir in os.listdir(models_dir):
    subdir_path = os.path.join(models_dir, subdir)
    if os.path.isdir(subdir_path) and not subdir.startswith('__'):
        for filename in os.listdir(subdir_path):
            if filename.endswith('.py') and not filename.startswith('__'):
                module_name = f"app.models.{subdir}.{filename[:-3]}"
                try:
                    importlib.import_module(module_name)
                except ImportError as e:
                    print(f"⚠️ Warning: Could not import {module_name}: {e}")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()


def get_sync_url() -> str:
    url = settings.database_url
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg")
    return url


def run_migrations_offline() -> None:
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_sync_url()
    
    from sqlalchemy import engine_from_config
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
