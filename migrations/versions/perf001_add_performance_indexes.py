"""Add missing performance indexes

Adds indexes for columns that are queried/filtered frequently but lack
index coverage, identified from slow-query and log analysis:
- ProfileView foreign keys (profile lookups, "who viewed my profile")
- DiscussionView foreign keys (view count queries)
- Discussion.is_closed (filtered in search and display)
- User.last_login_at (admin dashboard sorting)
- DailyBriefSubscriber composite (status, cadence) for the hourly brief job

Revision ID: perf001
Revises: u2v3w4x5y6z7
Create Date: 2026-04-21
"""
from alembic import op

revision = 'perf001'
down_revision = 'u2v3w4x5y6z7'
branch_labels = None
depends_on = None


def upgrade():
    # ProfileView — foreign key lookups for "who viewed my profile"
    op.create_index(
        'ix_profile_view_individual_profile_id',
        'profile_view',
        ['individual_profile_id'],
    )
    op.create_index(
        'ix_profile_view_company_profile_id',
        'profile_view',
        ['company_profile_id'],
    )
    op.create_index(
        'ix_profile_view_viewer_id',
        'profile_view',
        ['viewer_id'],
    )
    op.create_index(
        'ix_profile_view_timestamp',
        'profile_view',
        ['timestamp'],
    )

    # DiscussionView — filtered by discussion_id for view counts; viewer_id for user history
    op.create_index(
        'ix_discussion_view_discussion_id',
        'discussion_view',
        ['discussion_id'],
    )
    op.create_index(
        'ix_discussion_view_viewer_id',
        'discussion_view',
        ['viewer_id'],
    )
    op.create_index(
        'ix_discussion_view_timestamp',
        'discussion_view',
        ['timestamp'],
    )

    # Discussion.is_closed — filtered in search, homepage, and partner APIs
    op.create_index(
        'ix_discussion_is_closed',
        'discussion',
        ['is_closed'],
    )

    # User.last_login_at — admin dashboard sorting and filtering
    op.create_index(
        'ix_user_last_login_at',
        'user',
        ['last_login_at'],
    )

    # DailyBriefSubscriber — the hourly brief job filters by (status, cadence)
    # then does Python-side timezone filtering. A composite index lets Postgres
    # avoid a full table scan on every brief send cycle.
    op.create_index(
        'ix_dbs_status_cadence',
        'daily_brief_subscriber',
        ['status', 'cadence'],
    )


def downgrade():
    op.drop_index('ix_dbs_status_cadence', table_name='daily_brief_subscriber')
    op.drop_index('ix_user_last_login_at', table_name='user')
    op.drop_index('ix_discussion_is_closed', table_name='discussion')
    op.drop_index('ix_discussion_view_timestamp', table_name='discussion_view')
    op.drop_index('ix_discussion_view_viewer_id', table_name='discussion_view')
    op.drop_index('ix_discussion_view_discussion_id', table_name='discussion_view')
    op.drop_index('ix_profile_view_timestamp', table_name='profile_view')
    op.drop_index('ix_profile_view_viewer_id', table_name='profile_view')
    op.drop_index('ix_profile_view_company_profile_id', table_name='profile_view')
    op.drop_index('ix_profile_view_individual_profile_id', table_name='profile_view')
