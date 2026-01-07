"""Add personal_impact to brief_item

Revision ID: a1b2c3d4e5f6
Revises: 615fd0b16628
Create Date: 2026-01-07 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '615fd0b16628'
branch_labels = None
depends_on = None


def upgrade():
    # Add personal_impact column to brief_item table
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('personal_impact', sa.Text(), nullable=True))


def downgrade():
    # Remove personal_impact column from brief_item table
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.drop_column('personal_impact')
