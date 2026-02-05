"""Add normalized_url and url_hash to NewsArticle for Partner API lookup

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-02-05

This migration adds:
- normalized_url: Canonical URL form for partner embed lookups
- url_hash: SHA-256 hash (first 32 chars) for fast indexing

After migration, run backfill to populate existing articles:
    flask backfill-normalized-urls
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's4t5u6v7w8x9'
down_revision = 'r3s4t5u6v7w8'
branch_labels = None
depends_on = None


def upgrade():
    # Add normalized_url column
    op.add_column('news_article',
        sa.Column('normalized_url', sa.String(1000), nullable=True)
    )

    # Add url_hash column
    op.add_column('news_article',
        sa.Column('url_hash', sa.String(32), nullable=True)
    )

    # Create indexes for fast lookups
    # Note: For PostgreSQL, you could use postgresql_using='hash' for normalized_url
    # but btree is more portable and still fast for equality checks
    op.create_index(
        'idx_article_normalized_url',
        'news_article',
        ['normalized_url'],
        unique=False
    )

    op.create_index(
        'idx_article_url_hash',
        'news_article',
        ['url_hash'],
        unique=False
    )


def downgrade():
    # Drop indexes first
    op.drop_index('idx_article_url_hash', table_name='news_article')
    op.drop_index('idx_article_normalized_url', table_name='news_article')

    # Drop columns
    op.drop_column('news_article', 'url_hash')
    op.drop_column('news_article', 'normalized_url')
