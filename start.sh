#!/bin/bash

# 1. Run database migrations
echo "Running database migrations..."
alembic upgrade head

# 2. Start the app using Gunicorn with the new config file
echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
