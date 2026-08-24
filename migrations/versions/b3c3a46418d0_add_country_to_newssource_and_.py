"""Add country to NewsSource and DiscussionSourceArticle table

Revision ID: b3c3a46418d0
Revises: 8fda1aabee9a
Create Date: 2026-01-02 08:49:30.902467

Idempotent: `d8e9f0a1b2c3` (sibling branch from c3a2f6d73e0a) also adds
`news_source.country`. From-empty upgrades apply both branches before the
merge, so this revision must no-op when the column/table already exists.
Production already stamped this revision and will not re-execute it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'b3c3a46418d0'
down_revision = '8fda1aabee9a'
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    conn = op.get_bind()
    inspector = inspect(conn)
    return column_name in {c['name'] for c in inspector.get_columns(table_name)}


def _table_exists(table_name):
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    if not _table_exists('discussion_source_article'):
        op.create_table(
            'discussion_source_article',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('discussion_id', sa.Integer(), nullable=False),
            sa.Column('article_id', sa.Integer(), nullable=False),
            sa.Column('added_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['article_id'], ['news_article.id'], ),
            sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('discussion_id', 'article_id', name='uq_discussion_article'),
        )
        with op.batch_alter_table('discussion_source_article', schema=None) as batch_op:
            batch_op.create_index('idx_dsa_article', ['article_id'], unique=False)
            batch_op.create_index('idx_dsa_discussion', ['discussion_id'], unique=False)

    if not _column_exists('news_source', 'country'):
        with op.batch_alter_table('news_source', schema=None) as batch_op:
            batch_op.add_column(sa.Column('country', sa.String(length=100), nullable=True))


def downgrade():
    # Only drop objects this revision owns when present. Sibling branch d8e9
    # may still need news_source.country, so leave the column in place on
    # downgrade of this branch alone (full downgrade of both branches would
    # remove it via d8e9).
    if _table_exists('discussion_source_article'):
        with op.batch_alter_table('discussion_source_article', schema=None) as batch_op:
            batch_op.drop_index('idx_dsa_discussion')
            batch_op.drop_index('idx_dsa_article')
        op.drop_table('discussion_source_article')
