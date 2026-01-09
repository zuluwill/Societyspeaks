#!/bin/bash
set -e

echo "Running database migrations..."
flask db upgrade

echo "Starting Gunicorn..."
exec gunicorn --bind=0.0.0.0:5000 --reuse-port --timeout=120 run:app
