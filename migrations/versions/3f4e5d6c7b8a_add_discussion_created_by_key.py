"""Add created_by_key_id to discussion for API key audit attribution

Revision ID: 3f4e5d6c7b8a
Revises: c4d5e6f7a8b9
Create Date: 2026-04-07

Allows the partner portal to answer "which API key created this discussion?"
without exposing the raw key value. Join to partner_api_key for key_prefix
and key_last4. Nullable for RSS-ingested rows and legacy discussions created
before this migration.

Idempotent: sibling branch ordering can leave partner_api_key missing when
this runs; `r1e2p3a4i5r6` adds the column+FK once both tables exist.
Production already stamped this revision and will not re-execute it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '3f4e5d6c7b8a'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if 'discussion' not in tables or 'partner_api_key' not in tables:
        return
    cols = {c['name'] for c in inspector.get_columns('discussion')}
    if 'created_by_key_id' not in cols:
        op.add_column(
            'discussion',
            sa.Column('created_by_key_id', sa.Integer(), nullable=True),
        )
    fks = {fk['name'] for fk in inspector.get_foreign_keys('discussion')}
    if 'fk_discussion_created_by_key' not in fks:
        op.create_foreign_key(
            'fk_discussion_created_by_key',
            'discussion', 'partner_api_key',
            ['created_by_key_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'discussion' not in inspector.get_table_names():
        return
    fks = {fk['name'] for fk in inspector.get_foreign_keys('discussion')}
    if 'fk_discussion_created_by_key' in fks:
        op.drop_constraint('fk_discussion_created_by_key', 'discussion', type_='foreignkey')
    cols = {c['name'] for c in inspector.get_columns('discussion')}
    if 'created_by_key_id' in cols:
        op.drop_column('discussion', 'created_by_key_id')
