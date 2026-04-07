"""Add embed_disabled kill-switch column to partner

Revision ID: w9x0y1z2a3b4
Revises: de16e9f9813c
Create Date: 2026-04-07

"""
from alembic import op
import sqlalchemy as sa


revision = 'w9x0y1z2a3b4'
down_revision = 'de16e9f9813c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'partner',
        sa.Column('embed_disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Remove DB default after backfilling existing rows.
    op.alter_column('partner', 'embed_disabled', server_default=None)


def downgrade():
    op.drop_column('partner', 'embed_disabled')
