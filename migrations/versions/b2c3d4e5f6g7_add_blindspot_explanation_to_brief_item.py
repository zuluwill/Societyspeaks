"""Add blindspot_explanation to brief_item

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-07 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Add blindspot_explanation column to brief_item table
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('blindspot_explanation', sa.Text(), nullable=True))


def downgrade():
    # Remove blindspot_explanation column from brief_item table
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.drop_column('blindspot_explanation')
