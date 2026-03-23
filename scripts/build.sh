#!/bin/bash
set -e

echo "Installing Python dependencies..."
pip install --quiet --disable-pip-version-check -r requirements.txt

echo "Running database migrations..."
# Fix: if a previous bad deployment applied revision 'a1b2c3d4e5f6' as a ghost entry
# in alembic_version, remove it so flask db upgrade can proceed without an overlap error.
APP_ROLE=web SQLALCHEMY_MIGRATE=1 python3 -c "
from app import create_app, db
app = create_app()
with app.app_context():
    r = db.session.execute(db.text(\"SELECT 1 FROM alembic_version WHERE version_num='a1b2c3d4e5f6'\")).fetchone()
    if r:
        db.session.execute(db.text(\"DELETE FROM alembic_version WHERE version_num='a1b2c3d4e5f6'\"))
        db.session.commit()
        print('Fixed: removed ghost migration a1b2c3d4e5f6 from alembic_version')
" 2>&1 || true
SQLALCHEMY_MIGRATE=1 flask db upgrade

echo "Building Tailwind CSS..."
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --minify

echo "Build complete!"
