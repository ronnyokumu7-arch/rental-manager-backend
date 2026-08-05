#!/bin/bash
set -e

# Default to 8000 if Render doesn't provide $PORT
export PORT=${PORT:-8000}

# 1. Run database migrations
echo "🔄 Running database migrations..."
alembic upgrade head
echo "✅ Migrations complete."

# 2. Start the FastAPI server
# Note: Using uvicorn directly (not Gunicorn). 2 workers is ideal for I/O-bound async apps.
echo "🚀 Starting application on port $PORT with 2 workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 2