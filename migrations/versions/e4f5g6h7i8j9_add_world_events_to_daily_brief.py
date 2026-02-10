"""Add world_events JSON column to daily_brief

Adds a world_events JSON column to the daily_brief table for storing
curated geopolitical prediction market data ("What the World is Watching").
Nullable - no impact on existing briefs.

Revision ID: e4f5g6h7i8j9
Revises: d3e4f5g6h7i8
Create Date: 2026-02-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'e4f5g6h7i8j9'
down_revision = 'd3e4f5g6h7i8'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('daily_brief')]
    if 'world_events' not in columns:
        op.add_column('daily_brief', sa.Column('world_events', sa.JSON(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('daily_brief')]
    if 'world_events' in columns:
        op.drop_column('daily_brief', 'world_events')
