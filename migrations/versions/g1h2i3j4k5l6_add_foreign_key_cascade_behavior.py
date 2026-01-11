"""Add foreign key cascade behavior

Revision ID: g1h2i3j4k5l6
Revises: de16e9f9813c
Create Date: 2026-01-11

This migration adds proper ON DELETE behavior to foreign keys to prevent
orphaned records and ensure referential integrity.

Changes:
- TrendingTopicArticle.topic_id: CASCADE (auto-delete when topic deleted)
- TrendingTopicArticle.article_id: CASCADE (auto-delete when article deleted)
- BriefItem.brief_id: CASCADE (auto-delete when brief deleted)
- BriefItem.trending_topic_id: RESTRICT (prevent deleting topics used in briefs)
- DiscussionSourceArticle.discussion_id: CASCADE (auto-delete when discussion deleted)
- DiscussionSourceArticle.article_id: CASCADE (auto-delete when article deleted)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'g1h2i3j4k5l6'
down_revision = 'de16e9f9813c'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add ON DELETE constraints to foreign keys.
    
    Note: SQLite does not support ALTER COLUMN for foreign keys,
    so we need to recreate the tables. This migration handles both
    SQLite (for development) and PostgreSQL (for production).
    """
    # Get the database dialect
    bind = op.get_bind()
    dialect = bind.dialect.name
    
    if dialect == 'sqlite':
        # SQLite requires table recreation for FK changes
        # For now, skip - the ORM will handle cascades at app level
        # The constraints will apply to new databases
        print("SQLite detected - FK cascade constraints will apply to new databases only")
        return
    
    # PostgreSQL/MySQL - can modify foreign keys
    
    # TrendingTopicArticle.topic_id -> CASCADE
    op.drop_constraint('trending_topic_article_topic_id_fkey', 'trending_topic_article', type_='foreignkey')
    op.create_foreign_key(
        'trending_topic_article_topic_id_fkey',
        'trending_topic_article', 'trending_topic',
        ['topic_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # TrendingTopicArticle.article_id -> CASCADE
    op.drop_constraint('trending_topic_article_article_id_fkey', 'trending_topic_article', type_='foreignkey')
    op.create_foreign_key(
        'trending_topic_article_article_id_fkey',
        'trending_topic_article', 'news_article',
        ['article_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # BriefItem.brief_id -> CASCADE
    op.drop_constraint('brief_item_brief_id_fkey', 'brief_item', type_='foreignkey')
    op.create_foreign_key(
        'brief_item_brief_id_fkey',
        'brief_item', 'daily_brief',
        ['brief_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # BriefItem.trending_topic_id -> RESTRICT
    op.drop_constraint('brief_item_trending_topic_id_fkey', 'brief_item', type_='foreignkey')
    op.create_foreign_key(
        'brief_item_trending_topic_id_fkey',
        'brief_item', 'trending_topic',
        ['trending_topic_id'], ['id'],
        ondelete='RESTRICT'
    )
    
    # DiscussionSourceArticle.discussion_id -> CASCADE
    op.drop_constraint('discussion_source_article_discussion_id_fkey', 'discussion_source_article', type_='foreignkey')
    op.create_foreign_key(
        'discussion_source_article_discussion_id_fkey',
        'discussion_source_article', 'discussion',
        ['discussion_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # DiscussionSourceArticle.article_id -> CASCADE
    op.drop_constraint('discussion_source_article_article_id_fkey', 'discussion_source_article', type_='foreignkey')
    op.create_foreign_key(
        'discussion_source_article_article_id_fkey',
        'discussion_source_article', 'news_article',
        ['article_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    """Remove ON DELETE constraints from foreign keys."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    
    if dialect == 'sqlite':
        # No changes were made for SQLite
        return
    
    # Restore original foreign keys without ON DELETE
    
    # TrendingTopicArticle
    op.drop_constraint('trending_topic_article_topic_id_fkey', 'trending_topic_article', type_='foreignkey')
    op.create_foreign_key(
        'trending_topic_article_topic_id_fkey',
        'trending_topic_article', 'trending_topic',
        ['topic_id'], ['id']
    )
    
    op.drop_constraint('trending_topic_article_article_id_fkey', 'trending_topic_article', type_='foreignkey')
    op.create_foreign_key(
        'trending_topic_article_article_id_fkey',
        'trending_topic_article', 'news_article',
        ['article_id'], ['id']
    )
    
    # BriefItem
    op.drop_constraint('brief_item_brief_id_fkey', 'brief_item', type_='foreignkey')
    op.create_foreign_key(
        'brief_item_brief_id_fkey',
        'brief_item', 'daily_brief',
        ['brief_id'], ['id']
    )
    
    op.drop_constraint('brief_item_trending_topic_id_fkey', 'brief_item', type_='foreignkey')
    op.create_foreign_key(
        'brief_item_trending_topic_id_fkey',
        'brief_item', 'trending_topic',
        ['trending_topic_id'], ['id']
    )
    
    # DiscussionSourceArticle
    op.drop_constraint('discussion_source_article_discussion_id_fkey', 'discussion_source_article', type_='foreignkey')
    op.create_foreign_key(
        'discussion_source_article_discussion_id_fkey',
        'discussion_source_article', 'discussion',
        ['discussion_id'], ['id']
    )
    
    op.drop_constraint('discussion_source_article_article_id_fkey', 'discussion_source_article', type_='foreignkey')
    op.create_foreign_key(
        'discussion_source_article_article_id_fkey',
        'discussion_source_article', 'news_article',
        ['article_id'], ['id']
    )
