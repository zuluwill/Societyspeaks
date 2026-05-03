#!/bin/bash
# Post-merge setup script — runs automatically after a task agent merge.
# Must be: idempotent, non-interactive (stdin is closed), and fast.
set -e

echo "[post-merge] Installing Python dependencies..."
pip install --quiet --disable-pip-version-check -r requirements.txt

echo "[post-merge] Running database migrations..."
SQLALCHEMY_MIGRATE=1 flask db upgrade

echo "[post-merge] Compiling translation catalogs (.po -> .mo)..."
pybabel compile -d translations

echo "[post-merge] Installing Node.js dependencies..."
npm install --silent

echo "[post-merge] Building Tailwind CSS..."
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --minify

echo "[post-merge] Done."
