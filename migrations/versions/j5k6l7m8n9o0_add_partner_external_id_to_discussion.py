"""Add partner_external_id to discussion for non-article partner flows

Revision ID: j5k6l7m8n9o0
Revises: 3f4e5d6c7b8a
Create Date: 2026-04-07

Adds a partner-defined stable identifier so partners can create/manage
discussions that are not tied to a canonical article URL.
"""
from alembic import op
import sqlalchemy as sa


revision = 'j5k6l7m8n9o0'
down_revision = '3f4e5d6c7b8a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'discussion',
        sa.Column('partner_external_id', sa.String(length=128), nullable=True),
    )
    op.create_index(
        'idx_discussion_partner_external_id',
        'discussion',
        ['partner_external_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('idx_discussion_partner_external_id', table_name='discussion')
    op.drop_column('discussion', 'partner_external_id')
