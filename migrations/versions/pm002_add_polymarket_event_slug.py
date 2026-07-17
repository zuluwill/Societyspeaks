"""Add event_slug to polymarket_market for event-level URLs and dedupe.

Revision ID: pm002
Revises: dq001
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = 'pm002'
down_revision = 'dq001'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c['name'] for c in inspector.get_columns('polymarket_market')}
    if 'event_slug' not in columns:
        op.add_column(
            'polymarket_market',
            sa.Column('event_slug', sa.String(length=200), nullable=True),
        )
        op.create_index('idx_pm_market_event_slug', 'polymarket_market', ['event_slug'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    indexes = {i['name'] for i in inspector.get_indexes('polymarket_market')}
    if 'idx_pm_market_event_slug' in indexes:
        op.drop_index('idx_pm_market_event_slug', table_name='polymarket_market')
    columns = {c['name'] for c in inspector.get_columns('polymarket_market')}
    if 'event_slug' in columns:
        op.drop_column('polymarket_market', 'event_slug')
