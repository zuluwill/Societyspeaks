"""add analytics event and daily aggregate tables

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-03-09 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's2t3u4v5w6x7'
down_revision = 'r1s2t3u4v5w6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analytics_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_name', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('programme_id', sa.Integer(), nullable=True),
        sa.Column('discussion_id', sa.Integer(), nullable=True),
        sa.Column('statement_id', sa.Integer(), nullable=True),
        sa.Column('cohort_slug', sa.String(length=80), nullable=True),
        sa.Column('country', sa.String(length=80), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('event_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id']),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id']),
        sa.ForeignKeyConstraint(['statement_id'], ['statement.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_analytics_event_name_created', 'analytics_event', ['event_name', 'created_at'], unique=False)
    op.create_index('idx_analytics_event_programme_created', 'analytics_event', ['programme_id', 'created_at'], unique=False)
    op.create_index('idx_analytics_event_discussion_created', 'analytics_event', ['discussion_id', 'created_at'], unique=False)
    op.create_index('idx_analytics_event_user_created', 'analytics_event', ['user_id', 'created_at'], unique=False)
    op.create_index('idx_analytics_event_cohort_created', 'analytics_event', ['cohort_slug', 'created_at'], unique=False)

    op.create_table(
        'analytics_daily_aggregate',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('event_name', sa.String(length=64), nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=True),
        sa.Column('discussion_id', sa.Integer(), nullable=True),
        sa.Column('cohort_slug', sa.String(length=80), nullable=True),
        sa.Column('country', sa.String(length=80), nullable=True),
        sa.Column('event_count', sa.Integer(), nullable=False),
        sa.Column('unique_users', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id']),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'event_date',
            'event_name',
            'programme_id',
            'discussion_id',
            'cohort_slug',
            'country',
            name='uq_analytics_daily_dims'
        )
    )
    op.create_index('idx_analytics_daily_lookup', 'analytics_daily_aggregate', ['event_date', 'event_name', 'programme_id'], unique=False)
    op.create_index('idx_analytics_daily_discussion', 'analytics_daily_aggregate', ['discussion_id', 'event_date'], unique=False)


def downgrade():
    op.drop_index('idx_analytics_daily_discussion', table_name='analytics_daily_aggregate')
    op.drop_index('idx_analytics_daily_lookup', table_name='analytics_daily_aggregate')
    op.drop_table('analytics_daily_aggregate')

    op.drop_index('idx_analytics_event_cohort_created', table_name='analytics_event')
    op.drop_index('idx_analytics_event_user_created', table_name='analytics_event')
    op.drop_index('idx_analytics_event_discussion_created', table_name='analytics_event')
    op.drop_index('idx_analytics_event_programme_created', table_name='analytics_event')
    op.drop_index('idx_analytics_event_name_created', table_name='analytics_event')
    op.drop_table('analytics_event')
