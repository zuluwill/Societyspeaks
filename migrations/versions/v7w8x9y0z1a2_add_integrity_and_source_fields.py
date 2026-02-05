"""Add integrity_mode to Discussion and source to Statement

Adds:
- Discussion.integrity_mode for stricter rate limits on sensitive topics
- Statement.source for tracking seed statement origin (ai_generated, partner_provided, user_submitted)

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v7w8x9y0z1a2'
down_revision = 'u6v7w8x9y0z1'
branch_labels = None
depends_on = None


def upgrade():
    # Add integrity_mode to Discussion
    op.add_column(
        'discussion',
        sa.Column('integrity_mode', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add source to Statement for tracking origin
    # Values: 'ai_generated', 'partner_provided', 'user_submitted'
    op.add_column(
        'statement',
        sa.Column('source', sa.String(20), nullable=True)
    )
    op.create_index(
        'idx_statement_source',
        'statement',
        ['source']
    )


def downgrade():
    op.drop_index('idx_statement_source', table_name='statement')
    op.drop_column('statement', 'source')
    op.drop_column('discussion', 'integrity_mode')
