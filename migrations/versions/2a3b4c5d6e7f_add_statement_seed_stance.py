"""Add seed_stance to statement for partner pro/con/neutral labels

Revision ID: 2a3b4c5d6e7f
Revises: g1h2i3j4k5l6
Create Date: 2026-04-07

Stores optional stance from Partner API seed_statements[].position (pro|con|neutral).
Nullable for user-submitted and legacy rows.

Idempotent: `r1e2p3a4i5r6` also adds this column for databases that skipped this
revision. Production already stamped this revision and will not re-execute it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '2a3b4c5d6e7f'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'statement' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('statement')}
    if 'seed_stance' in cols:
        return
    op.add_column(
        'statement',
        sa.Column('seed_stance', sa.String(length=20), nullable=True),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'statement' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('statement')}
    if 'seed_stance' not in cols:
        return
    op.drop_column('statement', 'seed_stance')
