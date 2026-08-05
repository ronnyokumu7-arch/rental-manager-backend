#!/bin/bash
set -e  # Exit immediately if any command fails

# Render sets $PORT; default to 8000 for local testing
export PORT="${PORT:-8000}"
echo "🔧 Using PORT: $PORT"

# 1. Run database migrations
echo "🔄 Running database migrations..."
if ! alembic upgrade head; then
  echo "❌ Migration failed. Check DATABASE_URL and database connectivity."
  exit 1
fi
echo "✅ Migrations complete."

# 2. Start the FastAPI server with explicit host/port
echo "🚀 Starting application on 0.0.0.0:$PORT with 2 workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 2