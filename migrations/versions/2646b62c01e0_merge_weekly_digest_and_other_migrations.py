"""Merge weekly digest and other migrations

Revision ID: 2646b62c01e0
Revises: ba07c61956b4, o9p0q1r2s3t4
Create Date: 2026-01-23 14:44:48.530008

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2646b62c01e0'
down_revision = ('ba07c61956b4', 'o9p0q1r2s3t4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
