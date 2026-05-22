"""Add game challenge table for friend links.

Revision ID: g3c4h5a6l7l8
Revises: g2b3c4d5e6f7
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = 'g3c4h5a6l7l8'
down_revision = 'g2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_challenge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=48), nullable=False),
        sa.Column('creator_run_id', sa.Integer(), nullable=False),
        sa.Column('scenario_slug', sa.String(length=80), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('schedule_date', sa.Date(), nullable=True),
        sa.Column('creator_display_name', sa.String(length=48), nullable=False),
        sa.Column('creator_headline', sa.String(length=300), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['creator_run_id'], ['game_run.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('creator_run_id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('idx_game_challenge_token', 'game_challenge', ['token'], unique=True)
    op.create_index('idx_game_challenge_creator_run', 'game_challenge', ['creator_run_id'], unique=True)


def downgrade():
    op.drop_index('idx_game_challenge_creator_run', table_name='game_challenge')
    op.drop_index('idx_game_challenge_token', table_name='game_challenge')
    op.drop_table('game_challenge')
