"""Add partner fields to Discussion model

Adds partner_article_url and partner_id for Phase 2 partner-created discussions.

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'u6v7w8x9y0z1'
down_revision = 't5u6v7w8x9y0'
branch_labels = None
depends_on = None


def upgrade():
    # Add partner_article_url column with index
    op.add_column(
        'discussion',
        sa.Column('partner_article_url', sa.String(1000), nullable=True)
    )
    op.create_index(
        'idx_discussion_partner_article_url',
        'discussion',
        ['partner_article_url']
    )

    # Add partner_id column with index
    op.add_column(
        'discussion',
        sa.Column('partner_id', sa.String(50), nullable=True)
    )
    op.create_index(
        'idx_discussion_partner_id',
        'discussion',
        ['partner_id']
    )


def downgrade():
    op.drop_index('idx_discussion_partner_id', table_name='discussion')
    op.drop_column('discussion', 'partner_id')
    op.drop_index('idx_discussion_partner_article_url', table_name='discussion')
    op.drop_column('discussion', 'partner_article_url')
