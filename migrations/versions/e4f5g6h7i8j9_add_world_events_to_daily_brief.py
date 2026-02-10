"""Add world_events JSON column to daily_brief

Adds a world_events JSON column to the daily_brief table for storing
curated geopolitical prediction market data ("What the World is Watching").
Nullable - no impact on existing briefs.

Revision ID: e4f5g6h7i8j9
Revises: z3a4b5c6d7e8
Create Date: 2026-02-10
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4f5g6h7i8j9'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('daily_brief', sa.Column('world_events', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('daily_brief', 'world_events')
