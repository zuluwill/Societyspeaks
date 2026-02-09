"""Add brief sections, weekly support, and upcoming events

Adds:
- BriefItem: section, depth, quick_summary columns
- DailyBrief: brief_type, week_start_date, week_end_date, week_ahead, market_pulse columns
- DailyBriefSubscriber: cadence, preferred_weekly_day columns
- UpcomingEvent table for "The Week Ahead" section
- Updated unique constraint on daily_brief (date + brief_type)

All new columns are nullable or have defaults for backward compatibility.
Existing briefs continue to work with the legacy flat layout.

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2026-02-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'd3e4f5g6h7i8'
down_revision = 'c2d3e4f5g6h7'
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # BriefItem: section, depth, quick_summary
    # =========================================================================
    op.add_column('brief_item', sa.Column('section', sa.String(30), nullable=True))
    op.add_column('brief_item', sa.Column('depth', sa.String(15), nullable=True))
    op.add_column('brief_item', sa.Column('quick_summary', sa.Text(), nullable=True))

    # Make trending_topic_id nullable (some items like week_ahead don't reference topics)
    op.alter_column('brief_item', 'trending_topic_id',
                     existing_type=sa.Integer(),
                     nullable=True)

    # Index for section-based queries
    op.create_index('idx_brief_item_section', 'brief_item', ['brief_id', 'section'])

    # =========================================================================
    # DailyBrief: brief_type, weekly fields, new sections data
    # =========================================================================
    op.add_column('daily_brief', sa.Column('brief_type', sa.String(10), nullable=True, server_default='daily'))
    op.add_column('daily_brief', sa.Column('week_start_date', sa.Date(), nullable=True))
    op.add_column('daily_brief', sa.Column('week_end_date', sa.Date(), nullable=True))
    op.add_column('daily_brief', sa.Column('week_ahead', sa.JSON(), nullable=True))
    op.add_column('daily_brief', sa.Column('market_pulse', sa.JSON(), nullable=True))

    # Backfill existing rows with 'daily'
    op.execute("UPDATE daily_brief SET brief_type = 'daily' WHERE brief_type IS NULL")

    # Drop old unique constraint on date alone (if it exists)
    try:
        op.drop_constraint('uq_daily_brief_date', 'daily_brief', type_='unique')
    except Exception:
        pass  # Constraint may not exist in all environments

    # Create new composite unique constraint (date + brief_type)
    op.create_unique_constraint('uq_daily_brief_date_type', 'daily_brief', ['date', 'brief_type'])

    # Index for type + date queries
    op.create_index('idx_brief_type_date', 'daily_brief', ['brief_type', 'date'])

    # =========================================================================
    # DailyBriefSubscriber: cadence, preferred_weekly_day
    # =========================================================================
    op.add_column('daily_brief_subscriber', sa.Column('cadence', sa.String(10), nullable=True, server_default='daily'))
    op.add_column('daily_brief_subscriber', sa.Column('preferred_weekly_day', sa.Integer(), nullable=True, server_default='6'))

    # Backfill existing subscribers as 'daily'
    op.execute("UPDATE daily_brief_subscriber SET cadence = 'daily' WHERE cadence IS NULL")

    # =========================================================================
    # UpcomingEvent table
    # =========================================================================
    op.create_table(
        'upcoming_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('event_time', sa.String(50), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('region', sa.String(50), nullable=True),
        sa.Column('importance', sa.String(10), server_default='medium'),
        sa.Column('source', sa.String(20), server_default='admin'),
        sa.Column('source_url', sa.String(500), nullable=True),
        sa.Column('source_article_id', sa.Integer(), sa.ForeignKey('news_article.id'), nullable=True),
        sa.Column('status', sa.String(20), server_default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
    )
    op.create_index('idx_upcoming_event_date', 'upcoming_event', ['event_date'])
    op.create_index('idx_upcoming_event_status', 'upcoming_event', ['status'])


def downgrade():
    # Drop UpcomingEvent table
    op.drop_index('idx_upcoming_event_status', 'upcoming_event')
    op.drop_index('idx_upcoming_event_date', 'upcoming_event')
    op.drop_table('upcoming_event')

    # Remove subscriber columns
    op.drop_column('daily_brief_subscriber', 'preferred_weekly_day')
    op.drop_column('daily_brief_subscriber', 'cadence')

    # Remove brief columns
    op.drop_index('idx_brief_type_date', 'daily_brief')
    try:
        op.drop_constraint('uq_daily_brief_date_type', 'daily_brief', type_='unique')
    except Exception:
        pass
    # Restore old unique constraint
    op.create_unique_constraint('uq_daily_brief_date', 'daily_brief', ['date'])
    op.drop_column('daily_brief', 'market_pulse')
    op.drop_column('daily_brief', 'week_ahead')
    op.drop_column('daily_brief', 'week_end_date')
    op.drop_column('daily_brief', 'week_start_date')
    op.drop_column('daily_brief', 'brief_type')

    # Remove item columns
    op.drop_index('idx_brief_item_section', 'brief_item')
    op.alter_column('brief_item', 'trending_topic_id',
                     existing_type=sa.Integer(),
                     nullable=False)
    op.drop_column('brief_item', 'quick_summary')
    op.drop_column('brief_item', 'depth')
    op.drop_column('brief_item', 'section')
