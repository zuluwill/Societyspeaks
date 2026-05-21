"""Add game daily schedule table.

Revision ID: g2b3c4d5e6f7
Revises: g1a2m3e4p5l6
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = 'g2b3c4d5e6f7'
down_revision = 'g1a2m3e4p5l6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_daily_schedule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_date', sa.Date(), nullable=False),
        sa.Column('scenario_slug', sa.String(length=80), nullable=False),
        sa.Column('category_label', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schedule_date'),
    )
    op.create_index(
        'idx_game_daily_schedule_date',
        'game_daily_schedule',
        ['schedule_date'],
        unique=True,
    )


def downgrade():
    op.drop_index('idx_game_daily_schedule_date', table_name='game_daily_schedule')
    op.drop_table('game_daily_schedule')
