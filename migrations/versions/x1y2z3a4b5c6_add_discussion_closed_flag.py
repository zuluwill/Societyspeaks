"""Add is_closed to Discussion

Adds:
- Discussion.is_closed for closing discussions to new votes

Revision ID: x1y2z3a4b5c6
Revises: v7w8x9y0z1a2
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'x1y2z3a4b5c6'
down_revision = 'v7w8x9y0z1a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'discussion',
        sa.Column('is_closed', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade():
    op.drop_column('discussion', 'is_closed')
