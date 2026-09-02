"""Add trending_topic.market_match_attempted_at

Revision ID: m4k7t2p9q1r3
Revises: 30a9831d56e0
Create Date: 2026-09-02

Topics that match no Polymarket market never get a TopicMarketMatch row, so
the 30-minute batch matcher re-selected them every run for their full 7-day
window (~378 topics x 48 runs/day). This column records the last attempt so
the matcher can apply a retry window instead.

Nullable with no server default, so this is a metadata-only ADD COLUMN in
PostgreSQL — no table rewrite, no lock beyond a brief ACCESS EXCLUSIVE.
Idempotent: safe to re-run against a database that already has the column.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'm4k7t2p9q1r3'
down_revision = '30a9831d56e0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'trending_topic' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('trending_topic')}
    if 'market_match_attempted_at' in cols:
        return
    with op.batch_alter_table('trending_topic') as batch_op:
        batch_op.add_column(
            sa.Column('market_match_attempted_at', sa.DateTime(), nullable=True)
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'trending_topic' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('trending_topic')}
    if 'market_match_attempted_at' not in cols:
        return
    with op.batch_alter_table('trending_topic') as batch_op:
        batch_op.drop_column('market_match_attempted_at')
