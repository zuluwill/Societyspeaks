"""merge email send retry tracking

Revision ID: cff133064e02
Revises: add_failed_items, r3s4t5u6v7w8
Create Date: 2026-01-31 11:31:36.999780

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cff133064e02'
down_revision = ('add_failed_items', 'r3s4t5u6v7w8')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
