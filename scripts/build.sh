#!/bin/bash
set -e

echo "Installing Python dependencies..."
pip install --quiet --disable-pip-version-check -r requirements.txt

echo "Running database migrations..."
SQLALCHEMY_MIGRATE=1 flask db upgrade

echo "Building Tailwind CSS..."
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --minify

echo "Build complete!"
