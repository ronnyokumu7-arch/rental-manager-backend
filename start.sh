#!/bin/bash
echo "Running database migrations..."
alembic upgrade head
echo "Starting application..."
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT