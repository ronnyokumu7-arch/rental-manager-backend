#!/bin/bash
set -e

export PORT="${PORT:-8000}"
echo "🔧 Using PORT: $PORT"

# 1. Try running migrations first
if alembic upgrade head; then
  echo "✅ Migrations applied successfully."
else
  echo "⚠️ Migrations failed (likely fresh DB). Bootstrapping schema..."
  
  # Create tables from current models
  python scripts/init_db.py
  
  # Tell Alembic the DB is already at the latest revision
  echo "🏷️  Stamping Alembic to head revision..."
  alembic stamp head
  echo "✅ Schema bootstrapped and Alembic synced."
fi

# 2. Start FastAPI server
echo " Starting application on 0.0.0.0:$PORT with 2 workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1