"""Add link_type to brief_link_click

Adds a link_type column so click analytics can distinguish between
article links, view-in-browser links, and other internal navigation.

Revision ID: c4d5e6f7a8b9
Revises: 8c18ff57279b
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = '8c18ff57279b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('brief_link_click') as batch_op:
        batch_op.add_column(
            sa.Column('link_type', sa.String(50), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('brief_link_click') as batch_op:
        batch_op.drop_column('link_type')
