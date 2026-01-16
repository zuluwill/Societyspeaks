"""Merge briefing system v2 and source profile migrations

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1, g2h3i4j5k6l7
Create Date: 2025-01-16 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm7n8o9p0q1r2'
down_revision = ('l6m7n8o9p0q1', 'g2h3i4j5k6l7')
branch_labels = None
depends_on = None


def upgrade():
    """Merge migration - no schema changes needed."""
    pass


def downgrade():
    """Merge migration - no schema changes needed."""
    pass
