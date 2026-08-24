"""Add embed_disabled kill-switch column to partner

Revision ID: w9x0y1z2a3b4
Revises: de16e9f9813c
Create Date: 2026-04-07

This revision sits on a branch that can run before the `partner` table is
created (sibling branch a0b1c2d3e4f5). When `partner` is missing, no-op —
`r1e2p3a4i5r6` adds embed_disabled idempotently once the table exists.
Production already stamped this revision and will not re-execute it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'w9x0y1z2a3b4'
down_revision = 'de16e9f9813c'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'partner' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('partner')}
    if 'embed_disabled' in cols:
        return
    op.add_column(
        'partner',
        sa.Column('embed_disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Remove DB default after backfilling existing rows.
    op.alter_column('partner', 'embed_disabled', server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'partner' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('partner')}
    if 'embed_disabled' not in cols:
        return
    op.drop_column('partner', 'embed_disabled')
