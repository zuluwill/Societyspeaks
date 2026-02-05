"""Add partner_ref to StatementVote for partner attribution

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-02-05

This migration adds:
- partner_ref: Tracks which partner embed a vote came from (e.g., 'observer', 'time')
- Index for fast partner-based analytics queries
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 't5u6v7w8x9y0'
down_revision = 's4t5u6v7w8x9'
branch_labels = None
depends_on = None


def upgrade():
    # Add partner_ref column for tracking which partner embed a vote came from
    op.add_column('statement_vote',
        sa.Column('partner_ref', sa.String(50), nullable=True)
    )

    # Create index for partner-based analytics queries
    op.create_index(
        'idx_vote_partner_ref',
        'statement_vote',
        ['partner_ref'],
        unique=False
    )


def downgrade():
    op.drop_index('idx_vote_partner_ref', table_name='statement_vote')
    op.drop_column('statement_vote', 'partner_ref')
