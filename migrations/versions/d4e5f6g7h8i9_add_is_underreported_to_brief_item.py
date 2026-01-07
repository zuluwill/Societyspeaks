"""Add is_underreported to brief_item

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-01-07 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6g7h8i9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_underreported column to brief_item table
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_underreported', sa.Boolean(), nullable=True, server_default='0'))


def downgrade():
    # Remove is_underreported column from brief_item table
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.drop_column('is_underreported')
