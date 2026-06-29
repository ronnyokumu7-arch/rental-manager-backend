#!/bin/bash

# 1. Run database migrations
echo "Running database migrations..."
alembic upgrade head

# 2. Start the app using Gunicorn, binding to the correct host and port
echo "Starting application..."
exec gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
