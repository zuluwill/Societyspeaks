"""Merge migration branches

Revision ID: 6f46cde200dc
Revises: a4b5c6d7e8f9, e5f6g7h8i9j0, f1g2h3i4j5k6
Create Date: 2026-01-10 16:30:48.947097

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f46cde200dc'
down_revision = ('a4b5c6d7e8f9', 'e5f6g7h8i9j0', 'f1g2h3i4j5k6')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
