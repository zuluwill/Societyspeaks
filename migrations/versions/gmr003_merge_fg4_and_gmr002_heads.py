"""Merge fg4hi5jk6lm7 (index programme_steward) and gmr002 (variant_seed) heads

Revision ID: gmr003
Revises: fg4hi5jk6lm7, gmr002
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'gmr003'
down_revision = ('fg4hi5jk6lm7', 'gmr002')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
