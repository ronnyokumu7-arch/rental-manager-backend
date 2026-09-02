#!/bin/bash
set -e

export PORT="${PORT:-8000}"
echo "🔧 Using PORT: $PORT"

# A migration failure is a failed deployment. Never create tables and stamp
# Alembic as current: that hides failures and can corrupt schema state.
alembic upgrade head
echo "✅ Migrations applied successfully."

# 2. Start FastAPI server
echo " Starting application on 0.0.0.0:$PORT with 2 workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
