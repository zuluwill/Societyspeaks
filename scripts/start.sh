#!/bin/bash

echo "Running database migrations..."
if flask db upgrade; then
    echo "Migrations completed successfully"
else
    echo "Warning: Migrations failed or skipped, continuing anyway..."
fi

echo "Starting Gunicorn..."
exec gunicorn --bind=0.0.0.0:5000 --reuse-port --timeout=120 run:app
