#!/bin/bash
set -e

echo "Installing Python dependencies..."
pip install --quiet --disable-pip-version-check -r requirements.txt

echo "Running database migrations..."
# Never delete alembic_version rows here: a1b2c3d4e5f6 is a legitimate revision
# (personal_impact on brief_item). Use normal Alembic upgrades only.
SQLALCHEMY_MIGRATE=1 flask db upgrade

echo "Compiling translation catalogs (.po -> .mo)..."
pybabel compile -d translations

echo "Installing Node.js dependencies..."
npm install --silent

echo "Building Tailwind CSS..."
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --minify

echo "Build complete!"
