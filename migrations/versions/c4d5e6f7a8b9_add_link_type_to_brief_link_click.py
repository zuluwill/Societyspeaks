"""Add link_type to brief_link_click

Adds a link_type column so click analytics can distinguish between
article links, view-in-browser links, and other internal navigation.

Revision ID: c4d5e6f7a8b9
Revises: 8c18ff57279b
Create Date: 2026-03-25

Idempotent for from-empty installs: `brief_link_click` is created on a
sibling branch that may not have run yet. Production already stamped this
revision and will not re-execute it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'c4d5e6f7a8b9'
down_revision = '8c18ff57279b'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'brief_link_click' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('brief_link_click')}
    if 'link_type' in cols:
        return
    with op.batch_alter_table('brief_link_click') as batch_op:
        batch_op.add_column(
            sa.Column('link_type', sa.String(50), nullable=True)
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'brief_link_click' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('brief_link_click')}
    if 'link_type' not in cols:
        return
    with op.batch_alter_table('brief_link_click') as batch_op:
        batch_op.drop_column('link_type')
