"""Add compound (programme_id, event_name, user_id) index on analytics_event

The NSP dashboard funnel section queries COUNT(DISTINCT user_id) filtered by
both programme_id and event_name.  Without this index Postgres falls back to
scanning the full-programme event rows.  The covering user_id column allows an
index-only scan for the COUNT(DISTINCT user_id) aggregation.

Revision ID: t0u1v2w3x4y5
Revises: s2t3u4v5w6x7
Create Date: 2026-03-09

"""
from alembic import op

revision = 't0u1v2w3x4y5'
down_revision = 's2t3u4v5w6x7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'idx_analytics_event_programme_name_user',
        'analytics_event',
        ['programme_id', 'event_name', 'user_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('idx_analytics_event_programme_name_user', table_name='analytics_event')
